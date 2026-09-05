import logging
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.core.permissions import (
    can_access_repair,
    can_assign_masters,
    can_delete_client,
    can_delete_repair,
    can_edit_finances,
    can_finish_repair,
    is_master_only,
)
from app.db.models import (
    Client,
    City,
    Notification,
    Payment,
    PrintJob,
    Repair,
    RepairEvent,
    RepairMaster,
    RepairPart,
    RepairPartOrder,
    RepairPhoto,
    User,
    UserRole,
)
from app.schemas.repair import (
    PartOrderCreate,
    PartOrderOut,
    PartOrderUpdate,
    PhotoOut,
    RepairCreate,
    RepairEventOut,
    RepairOut,
    RepairUpdate,
    RepairsPage,
)
from app.services import audit
from app.services.chat import send_assignment_notice
from app.services.numbering import next_repair_number, new_public_token, normalize_phone
from app.services.sms import (
    build_ready_sms,
    send_master_assignment_sms,
    send_sms,
)
from app.services.settings import get_repair_statuses, get_storage_months
from app.services.storage import (
    object_key_for,
    public_url,
    remove_objects,
    save_object,
)
from app.ws.manager import manager

log = logging.getLogger("msb.repairs")

router = APIRouter(prefix="/repairs", tags=["repairs"])

# Сколько раз пробуем выделить номер ремонта при одновременной приёмке.
MAX_NUMBER_ATTEMPTS = 5


# Проверки прав вынесены в app.core.permissions — единая матрица «роль ×
# операция». Обёртки ниже оставлены, чтобы не переписывать все вызовы в файле.
def _is_master_only(user) -> bool:
    return is_master_only(user)


def _can_access(user, repair: Repair) -> bool:
    """Мастера видят только свои ремонты; остальные роли — все."""
    return can_access_repair(user, repair)


def _is_assigner(user) -> bool:
    """Кто может назначать мастеров на ремонт (не сам мастер)."""
    return user.has_role(
        UserRole.ADMIN.value,
        UserRole.MANAGER.value,
        UserRole.OPERATOR.value,
    )


def _can_assign_masters(user) -> bool:
    """Назначить мастеров/помощников на ремонт могут только admin и operator."""
    return can_assign_masters(user)


def _num(value):
    """Decimal/float/bool -> JSON-безопасное значение для meta аудита."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


# Финансовые поля ремонта: цена, себестоимость, выплата мастерам, «оплачено».
FINANCIAL_FIELDS = ("price_final", "cost_amount", "master_payout", "paid")
# Цена «вилки» тоже влияет на деньги и на печать в бланке.
FINANCIAL_FIELDS += ("price_min", "price_max")


def _master_scope(user_id) -> "object":
    """SQL-условие: ремонт назначен мастеру напрямую или через repair_masters."""
    from sqlalchemy import or_, select as _select

    subq = _select(RepairMaster.repair_id).where(RepairMaster.user_id == user_id)
    return or_(Repair.master_id == user_id, Repair.id.in_(subq))


def _serialize(repair: Repair) -> RepairOut:
    events = [
        RepairEventOut(
            id=e.id, type=e.type, actor_id=e.actor_id, data=e.data, created_at=e.created_at
        )
        for e in repair.events
    ]
    all_links = list(repair.masters)
    master_links = [m for m in all_links if (m.kind or "master") != "helper"]
    helper_links = [m for m in all_links if (m.kind or "master") == "helper"]
    master_ids = [m.user_id for m in master_links]
    master_names = [m.user.name for m in master_links if m.user]
    helper_ids = [m.user_id for m in helper_links]
    helper_names = [m.user.name for m in helper_links if m.user]
    # Основной мастер всегда первым, даже если связей ещё нет (старые ремонты).
    if repair.master_id and repair.master_id not in master_ids:
        master_ids.insert(0, repair.master_id)
        if repair.master:
            master_names.insert(0, repair.master.name)

    return RepairOut(
        id=repair.id,
        number=repair.number,
        public_token=repair.public_token,
        city_id=repair.city_id,
        branch_id=repair.branch_id,
        client_id=repair.client_id,
        device_type=repair.device_type,
        brand=repair.brand,
        model=repair.model,
        serial=repair.serial,
        complectation=repair.complectation,
        fault_client=repair.fault_client,
        fault_master=repair.fault_master,
        condition_notes=repair.condition_notes,
        consent_repair_at=repair.consent_repair_at,
        accepted_by=repair.accepted_by,
        master_id=repair.master_id,
        status=repair.status,
        eta_days=repair.eta_days,
        eta_source=repair.eta_source,
        price_min=repair.price_min,
        price_max=repair.price_max,
        price_final=repair.price_final,
        cost_amount=repair.cost_amount,
        master_payout=repair.master_payout,
        paid=repair.paid,
        work_done=repair.work_done,
        warranty_text=repair.warranty_text,
        accepted_at=repair.accepted_at,
        ready_at=repair.ready_at,
        issued_at=repair.issued_at,
        storage_until=repair.storage_until,
        print_count=repair.print_count,
        source=repair.source,
        events=events,
        contact2_name=repair.contact2_name,
        contact2_phone=repair.contact2_phone,
        is_delivery=repair.is_delivery,
        client_name=repair.client.full_name,
        client_phone=repair.client.phone,
        master_name=repair.master.name if repair.master else None,
        master_ids=master_ids,
        master_names=master_names,
        helper_ids=helper_ids,
        helper_names=helper_names,
    )


async def _get_repair_or_404(db, repair_id: uuid.UUID) -> Repair:
    row = await db.execute(
        select(Repair)
        .where(Repair.id == repair_id)
        .options(
            selectinload(Repair.client),
            selectinload(Repair.master),
            selectinload(Repair.events),
            selectinload(Repair.masters).selectinload(RepairMaster.user),
        )
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    return repair


@router.get("/clients/lookup")
async def lookup_client(
    db: DbSession,
    user: CurrentUser,
    phone: str = Query(..., description="Телефон для поиска клиента"),
):
    """Найти клиента по телефону + вернуть список его ремонтов."""
    from app.services.numbering import normalize_phone
    phone_norm = normalize_phone(phone)

    # Сначала ищем по нормализованному номеру
    row = await db.execute(
        select(Client)
        .where(Client.phone_norm == phone_norm, Client.deleted_at.is_(None))
        .options(selectinload(Client.repairs))
    )
    client = row.scalar_one_or_none()

    # Если не нашли — попробуем поиск по подстроке
    if client is None:
        from sqlalchemy import func
        like = f"%{phone.strip()}%"
        row = await db.execute(
            select(
                Client.id,
                Client.full_name,
                Client.phone,
                func.count(Repair.id).label("repairs_count"),
            )
            .outerjoin(Repair, Repair.client_id == Client.id)
            .where(Client.phone.ilike(like), Client.deleted_at.is_(None))
            .group_by(Client.id, Client.full_name, Client.phone)
            .limit(5)
        )
        candidates = row.all()
        if candidates:
            return {
                "found": True,
                "multiple": True,
                "candidates": [
                    {
                        "id": str(cid),
                        "full_name": cname,
                        "phone": cphone,
                        "repairs_count": rcnt,
                    }
                    for cid, cname, cphone, rcnt in candidates
                ],
            }
        return {"found": False, "phone": phone, "phone_norm": phone_norm}

    # Клиент найден — возвращаем его ремонты
    repairs = []
    for r in sorted(client.repairs, key=lambda x: x.accepted_at, reverse=True):
        repairs.append({
            "id": str(r.id),
            "number": r.number,
            "status": r.status,
            "device_type": r.device_type,
            "brand": r.brand,
            "model": r.model,
            "accepted_at": r.accepted_at.isoformat() if r.accepted_at else None,
            "price_final": r.price_final,
            "paid": r.paid,
        })

    return {
        "found": True,
        "multiple": False,
        "client": {
            "id": str(client.id),
            "full_name": client.full_name,
            "phone": client.phone,
        },
        "repairs": repairs,
        "repairs_count": len(repairs),
    }


@router.get("/clients/list")
async def list_clients(
    db: DbSession,
    user: CurrentUser,
    q: str | None = Query(None, description="Поиск по имени или телефону"),
    limit: int = Query(100, le=500),
):
    """Список всех клиентов с количеством ремонтов."""
    from sqlalchemy import func
    q_stmt = (
        select(
            Client.id,
            Client.full_name,
            Client.phone,
            Client.phone_norm,
            func.count(Repair.id).label("repairs_count"),
        )
        .outerjoin(Repair, Repair.client_id == Client.id)
        .group_by(Client.id, Client.full_name, Client.phone, Client.phone_norm)
        .order_by(func.count(Repair.id).desc(), Client.full_name)
    )
    q_stmt = q_stmt.where(Client.deleted_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        q_stmt = q_stmt.where(
            (Client.full_name.ilike(like)) | (Client.phone.ilike(like))
        )
    q_stmt = q_stmt.limit(limit)
    row = await db.execute(q_stmt)
    return [
        {
            "id": str(cid),
            "full_name": cname,
            "phone": cphone,
            "repairs_count": rcnt,
        }
        for cid, cname, cphone, _pnorm, rcnt in row.all()
    ]


@router.get("/clients/{client_id}/repairs", response_model=list[RepairOut])
async def client_repairs(
    client_id: uuid.UUID, db: DbSession, user: CurrentUser
):
    """Все ремонты конкретного клиента."""
    row = await db.execute(select(Client).where(Client.id == client_id))
    client = row.scalar_one_or_none()
    if client is None:
        raise HTTPException(404, "Клиент не найден")
    repairs_q = (
        select(Repair)
        .where(Repair.client_id == client_id)
        .options(
            selectinload(Repair.client),
            selectinload(Repair.master),
            selectinload(Repair.events),
            selectinload(Repair.masters).selectinload(RepairMaster.user),
        )
        .order_by(Repair.accepted_at.desc())
    )
    if _is_master_only(user):
        repairs_q = repairs_q.where(_master_scope(user.id))
    r = await db.execute(repairs_q)
    return [_serialize(x) for x in r.scalars().all()]



def _require_admin(user) -> None:
    if not user.has_role(UserRole.ADMIN.value):
        raise HTTPException(403, "Только администратор")


class ClientUpdate(BaseModel):
    """Переименование/правка контакта клиента.

    Отдельный эндпоинт нужен потому, что раньше единственным способом
    изменить имя было создать ремонт на тот же номер — и имя перезаписывалось
    молча, вместе со всей историей прежнего человека.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=5, max_length=32)


@router.patch("/clients/{client_id}")
async def update_client(
    client_id: uuid.UUID, payload: ClientUpdate, db: DbSession, user: CurrentUser
):
    """Изменить имя/телефон клиента — админ, менеджер или оператор."""
    if not user.has_role(
        UserRole.ADMIN.value, UserRole.MANAGER.value, UserRole.OPERATOR.value
    ):
        raise HTTPException(403, "Недостаточно прав для изменения данных клиента")

    row = await db.execute(
        select(Client).where(Client.id == client_id, Client.deleted_at.is_(None))
    )
    client = row.scalar_one_or_none()
    if client is None:
        raise HTTPException(404, "Клиент не найден")

    data = payload.model_dump(exclude_unset=True)
    old_full_name = client.full_name
    old_phone = client.phone

    new_phone = data.get("phone")
    if new_phone is not None:
        phone_norm = normalize_phone(new_phone)
        if not phone_norm:
            raise HTTPException(400, "В телефоне нет ни одной цифры")
        clash = await db.execute(
            select(Client).where(
                Client.phone_norm == phone_norm, Client.id != client_id
            )
        )
        if clash.scalar_one_or_none() is not None:
            raise HTTPException(409, "Клиент с таким номером уже есть")
        client.phone = new_phone
        client.phone_norm = phone_norm

    if data.get("full_name") is not None:
        client.full_name = data["full_name"].strip()

    # RepairEvent привязан к конкретному ремонту, поэтому изменение карточки
    # клиента фиксируем только в журнале аудита.
    await audit.record(
        db,
        "client.update",
        actor_id=user.id,
        entity="client",
        entity_id=client_id,
        meta={
            "full_name_before": old_full_name,
            "full_name_after": client.full_name,
            "phone_before": old_phone,
            "phone_after": client.phone,
        },
    )
    await db.commit()
    await db.refresh(client)
    return {
        "id": str(client.id),
        "full_name": client.full_name,
        "phone": client.phone,
        "phone_norm": client.phone_norm,
    }


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: uuid.UUID, db: DbSession, user: CurrentUser
):
    """Удалить клиента (мягкое удаление) — только админ."""
    if not can_delete_client(user):
        raise HTTPException(403, "Только администратор")
    from app.db.base import utcnow

    row = await db.execute(select(Client).where(Client.id == client_id))
    client = row.scalar_one_or_none()
    if client is None or client.deleted_at is not None:
        raise HTTPException(404, "Клиент не найден")
    client.deleted_at = utcnow()
    await audit.record(
        db,
        audit.ACTION_CLIENT_DELETE,
        actor_id=user.id,
        entity="client",
        entity_id=client_id,
        meta={"full_name": client.full_name, "phone": client.phone},
    )
    await db.commit()
    return {"ok": True}


@router.delete("/{repair_id}")
async def delete_repair(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Полное удаление ремонта со всеми зависимостями — только админ."""
    if not can_delete_repair(user):
        raise HTTPException(403, "Только администратор")
    repair = await db.get(Repair, repair_id)
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")

    # Фото лежат на диске: строки RepairPhoto удалятся, а файлы остались бы
    # навсегда. Собираем ключи ДО удаления строк.
    photo_rows = await db.execute(
        select(RepairPhoto.object_key).where(RepairPhoto.repair_id == repair_id)
    )
    object_keys = [k for (k,) in photo_rows.all() if k]

    # Снимок ключевых полей — после удаления восстановить их будет неоткуда,
    # а `repair_events` уходит вместе с ремонтом.
    snapshot = {
        "number": repair.number,
        "status": repair.status,
        "client_id": str(repair.client_id),
        "price_final": float(repair.price_final) if repair.price_final is not None else None,
        "cost_amount": float(repair.cost_amount) if repair.cost_amount is not None else None,
        "master_payout": float(repair.master_payout) if repair.master_payout is not None else None,
        "paid": bool(repair.paid),
        "photos": len(object_keys),
    }

    for model in (
        Notification,
        PrintJob,
        Payment,
        RepairPart,
        RepairPartOrder,
        RepairPhoto,
        RepairMaster,
        RepairEvent,
    ):
        await db.execute(
            delete(model).where(model.repair_id == repair_id)
        )
    await db.delete(repair)
    await audit.record(
        db,
        audit.ACTION_REPAIR_DELETE,
        actor_id=user.id,
        entity="repair",
        entity_id=repair_id,
        meta=snapshot,
    )
    await db.commit()

    # Файлы удаляем уже после commit — чтобы откат транзакции не оставил
    # записи в БД без картинок.
    remove_objects(object_keys)

    await manager.broadcast({"type": "repair.deleted", "repair": {"id": str(repair_id)}})
    return {"ok": True}


@router.post("", response_model=RepairOut, status_code=201)
async def create_repair(
    payload: RepairCreate,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Приёмка техники.

    Номер ремонта выделяется последовательно по (тип, город, год), поэтому при
    одновременной приёмке двумя операторами возможен конфликт уникального
    индекса — в этом случае пробуем ещё раз с новым номером.
    """
    # Идемпотентность: повторная отправка с тем же ключом отдаёт готовый ремонт.
    if idempotency_key:
        row = await db.execute(
            select(Repair).where(Repair.idempotency_key == idempotency_key)
        )
        existing = row.scalar_one_or_none()
        if existing is not None:
            existing = await _get_repair_or_404(db, existing.id)
            return _serialize(existing)

    city = await db.get(City, payload.city_id)
    if city is None:
        raise HTTPException(400, "Город не найден")

    # Телефон обязан содержать цифры: иначе phone_norm получается пустым, и все
    # такие клиенты сливаются в одну запись (phone_norm — UNIQUE).
    phone_norm = normalize_phone(payload.client.phone)
    if not phone_norm:
        raise HTTPException(400, "В телефоне клиента нет ни одной цифры")

    # Мастера назначает только администратор или оператор. Мастер, принявший
    # технику, себя НЕ назначает автоматически — «Мастер» остаётся пустым.
    if payload.master_id is not None and not _can_assign_masters(user):
        raise HTTPException(403, "Мастера назначает администратор или оператор")

    repair_id: uuid.UUID | None = None
    last_error: Exception | None = None
    for attempt in range(MAX_NUMBER_ATTEMPTS):
        try:
            repair_id = await _persist_repair(
                db, payload, user, city, phone_norm, idempotency_key
            )
            break
        except IntegrityError as exc:
            # Откатываем и пробуем заново: счётчик номера сдвинется.
            await db.rollback()
            last_error = exc
            log.warning(
                "конфликт номера ремонта (попытка %d/%d): %s",
                attempt + 1, MAX_NUMBER_ATTEMPTS, exc,
            )
    if repair_id is None:
        raise HTTPException(
            409,
            "Не удалось выделить номер ремонта — приёмку пытаются оформить "
            "одновременно. Повторите попытку.",
        ) from last_error

    repair = await _get_repair_or_404(db, repair_id)

    # --- побочные эффекты ПОСЛЕ успешного commit (не повторяются при retry) ---
    # Мастеру назначен ремонт (сразу при приёмке): в личку сообщаем только
    # если назначил кто-то другой, а вот SMS на телефон мастера (если указан
    # в профиле) уходит в любом случае — даже когда мастер принял заявку сам.
    if repair.master is not None:
        if _is_assigner(user) and repair.master.id != user.id:
            await send_assignment_notice(db, actor=user, master=repair.master, repair=repair)
        await send_master_assignment_sms(repair.master, repair, db=db)

    await manager.broadcast(
        {
            "type": "repair.created",
            "repair": {"number": repair.number, "status": repair.status},
        }
    )
    return _serialize(repair)


async def _persist_repair(
    db,
    payload: RepairCreate,
    user,
    city: City,
    phone_norm: str,
    idempotency_key: str | None,
) -> uuid.UUID:
    """Создать клиента (при необходимости) и ремонт. Возвращает id ремонта.

    Бросает `IntegrityError` при конфликте номера — вызывающий код повторяет
    попытку. Ничего, кроме БД, здесь не происходит: SMS и рассылки делаются
    снаружи, чтобы не дублироваться при повторе.
    """
    from app.db.base import utcnow

    # --- Клиент: ищем по нормализованному номеру ---
    row = await db.execute(
        select(Client).where(
            Client.phone_norm == phone_norm, Client.deleted_at.is_(None)
        )
    )
    client = row.scalar_one_or_none()
    new_name = (payload.client.full_name or "").strip()
    if client is None:
        client = Client(
            full_name=new_name,
            phone=payload.client.phone,
            phone_norm=phone_norm,
        )
        db.add(client)
        await db.flush()
    elif new_name and new_name != client.full_name:
        # Раньше имя перезаписывалось молча: приём техники от другого человека
        # с тем же номером стирал прежнее имя вместе со всей его историей.
        # Теперь имя остаётся прежним, а расхождение фиксируется в аудите —
        # правится явно через PATCH /repairs/clients/{id}.
        await audit.record(
            db,
            audit.ACTION_CLIENT_MERGE_BLOCKED,
            actor_id=user.id,
            entity="client",
            entity_id=client.id,
            meta={
                "kept_name": client.full_name,
                "submitted_name": new_name,
                "phone_norm": phone_norm,
            },
        )

    number = await next_repair_number(db, city, payload.device_type)
    storage_months = await get_storage_months(db)
    now = utcnow()

    master_id = payload.master_id
    # Как только у ремонта есть основной мастер — он сразу начинает работу,
    # поэтому создаём ремонт сразу в «Диагностика», а не в «Принято».
    initial_status = "Диагностика" if master_id else "Принято"

    repair = Repair(
        number=number,
        public_token=new_public_token(),
        city_id=payload.city_id,
        branch_id=payload.branch_id,
        client_id=client.id,
        device_type=payload.device_type,
        brand=payload.brand,
        model=payload.model,
        serial=payload.serial,
        complectation=payload.complectation,
        fault_client=payload.fault_client,
        condition_notes=payload.condition_notes,
        contact2_name=payload.contact2_name,
        contact2_phone=payload.contact2_phone,
        is_delivery=payload.is_delivery,
        consent_repair_at=now if payload.consent_repair else None,
        accepted_by=user.id,
        master_id=master_id,
        status=initial_status,
        eta_days=payload.eta_days,
        eta_source=payload.eta_source,
        accepted_at=now,
        storage_until=now + timedelta(days=storage_months * 30),
        source=payload.source,
        idempotency_key=idempotency_key,
    )
    db.add(repair)
    await db.flush()

    db.add(
        RepairEvent(
            repair_id=repair.id,
            type="status_change",
            actor_id=user.id,
            data={"to": "Принято", "from": None},
        )
    )
    if initial_status != "Принято":
        db.add(
            RepairEvent(
                repair_id=repair.id,
                type="status_change",
                actor_id=user.id,
                data={"to": initial_status, "from": "Принято"},
            )
        )
    if master_id:
        db.add(
            RepairMaster(repair_id=repair.id, user_id=master_id, position=0)
        )
    await db.commit()
    return repair.id


# Группы-этапы для страницы «Все ремонты» (вкладки).
STAGE_STATUSES: dict[str, list[str]] = {
    "new": ["Принято"],
    "diag": ["Диагностика"],
    "work": ["Согласование", "Ожидание запчастей", "В ремонте"],
    "done": ["Готово к выдаче", "Выдано", "Не забрано", "Архив", "Отказ"],
}


def _parse_master_ids(raw: str | None) -> list[uuid.UUID]:
    """'id1,id2' -> [UUID, UUID] (мультивыбор мастеров в фильтре списка)."""
    if not raw:
        return []
    try:
        return [uuid.UUID(c.strip()) for c in raw.split(",") if c.strip()]
    except ValueError:
        raise HTTPException(400, "Некорректный id мастера")


def _repairs_filters(
    user,
    stage: str | None,
    status: str | None,
    master_id: uuid.UUID | None,
    master_ids: list[uuid.UUID],
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    date_field: str,
    unassigned: bool,
) -> list:
    """Общий срез для GET /repairs и GET /repairs/stats — одно и то же
    условие, чтобы карточки-суммарики совпадали с таблицей."""
    from sqlalchemy import or_

    filters = []
    if stage and stage != "all" and stage in STAGE_STATUSES:
        filters.append(Repair.status.in_(STAGE_STATUSES[stage]))
    if status:
        filters.append(Repair.status == status)
    if master_id:
        filters.append(Repair.master_id == master_id)
    if master_ids:
        subq = select(RepairMaster.repair_id).where(RepairMaster.user_id.in_(master_ids))
        filters.append(or_(Repair.master_id.in_(master_ids), Repair.id.in_(subq)))
    if date_from is not None or date_to is not None:
        # «по приёму» — accepted_at, «по закрытию» — ready_at
        # (готово к выдаче).
        col = Repair.ready_at if date_field == "ready" else Repair.accepted_at
        if date_from is not None:
            filters.append(col >= datetime.combine(date_from, datetime.min.time()))
        if date_to is not None:
            filters.append(col < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if unassigned:
        filters.append(Repair.master_id.is_(None))
        filters.append(Repair.id.not_in(select(RepairMaster.repair_id)))
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Repair.client.has(Client.phone.ilike(like)),
                Repair.client.has(Client.full_name.ilike(like)),
                Repair.brand.ilike(like),
                Repair.model.ilike(like),
            )
        )
    # Мастера видят только свои ремонты (назначен напрямую или через список).
    if _is_master_only(user):
        filters.append(_master_scope(user.id))
    return filters


@router.get("", response_model=RepairsPage)
async def list_repairs(
    db: DbSession,
    user: CurrentUser,
    stage: str | None = Query(
        None, pattern="^(new|diag|work|done|all)$", description="Фильтр по этапу"
    ),
    status: str | None = None,
    master_id: uuid.UUID | None = None,
    master_ids: str | None = Query(
        None, description="Список id мастеров через запятую (мультивыбор)"
    ),
    date_from: date | None = None,
    date_to: date | None = None,
    date_field: str = Query("accepted", pattern="^(accepted|ready)$"),
    unassigned: bool = False,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    mid_list = _parse_master_ids(master_ids)
    filters = _repairs_filters(
        user, stage, status, master_id, mid_list, q,
        date_from, date_to, date_field, unassigned,
    )
    base = select(Repair).where(*filters)

    total_row = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_row.scalar() or 0

    q_stmt = (
        base.options(
            selectinload(Repair.client),
            selectinload(Repair.master),
            selectinload(Repair.accepted_by_user),
            selectinload(Repair.events),
            selectinload(Repair.masters).selectinload(RepairMaster.user),
        )
        .order_by(Repair.accepted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    row = await db.execute(q_stmt)
    repairs_rows = row.scalars().all()
    items = [_serialize(r) for r in repairs_rows]
    # Дополнительно для таблицы: кто принял технику + запчасти ремонта
    # (стоимость и какие).
    if repairs_rows:
        rp_rows = await db.execute(
            select(RepairPart)
            .options(selectinload(RepairPart.part))
            .where(RepairPart.repair_id.in_([r.id for r in repairs_rows]))
        )
        parts_by_repair: dict[uuid.UUID, list[RepairPart]] = {}
        for rp in rp_rows.scalars().all():
            parts_by_repair.setdefault(rp.repair_id, []).append(rp)
        for r, out in zip(repairs_rows, items):
            out.accepted_by_name = r.accepted_by_user.name if r.accepted_by_user else None
            rps = parts_by_repair.get(r.id)
            if rps:
                cost = 0.0
                names = []
                for rp in rps:
                    if rp.price is not None:
                        cost += float(rp.price) * rp.qty
                    pname = rp.part.name if rp.part else "запчасть"
                    names.append(f"{pname} ×{rp.qty}" if rp.qty > 1 else pname)
                out.parts_cost = round(cost, 2)
                out.parts_names = names
    return RepairsPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats")
async def repairs_stats(
    db: DbSession,
    user: CurrentUser,
    stage: str | None = Query(
        None, pattern="^(new|diag|work|done|all)$", description="Фильтр по этапу"
    ),
    status: str | None = None,
    master_id: uuid.UUID | None = None,
    master_ids: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    date_field: str = Query("accepted", pattern="^(accepted|ready)$"),
    unassigned: bool = False,
    q: str | None = None,
):
    """5 суммариков по тому же срезу, что и GET /repairs (карточки на вкладке)."""
    mid_list = _parse_master_ids(master_ids)
    filters = _repairs_filters(
        user, stage, status, master_id, mid_list, q,
        date_from, date_to, date_field, unassigned,
    )
    ids_sub = select(Repair.id).where(*filters).subquery()

    total_row = await db.execute(
        select(
            func.coalesce(
                func.sum(func.coalesce(Repair.price_final, Repair.price_max, 0.0)), 0.0
            )
        ).where(Repair.id.in_(ids_sub))
    )
    payout_row = await db.execute(
        select(func.coalesce(func.sum(Repair.master_payout), 0.0)).where(
            Repair.id.in_(ids_sub)
        )
    )
    clients_row = await db.execute(
        select(func.count(func.distinct(Repair.client_id))).where(Repair.id.in_(ids_sub))
    )
    parts_row = await db.execute(
        select(
            func.coalesce(func.sum(func.coalesce(RepairPart.price, 0.0) * RepairPart.qty), 0.0)
        ).where(RepairPart.repair_id.in_(ids_sub))
    )

    total_sum = float(total_row.scalar() or 0)
    payout_sum = float(payout_row.scalar() or 0)
    parts_cost = float(parts_row.scalar() or 0)
    return {
        "total_sum": round(total_sum, 2),
        "parts_cost": round(parts_cost, 2),
        "master_payout": round(payout_sum, 2),
        # Прибыль = сумма ремонтов − расходы на запчасти − выплаты мастерам.
        "profit": round(total_sum - parts_cost - payout_sum, 2),
        "clients_unique": int(clients_row.scalar() or 0),
    }


@router.get("/stage-counts")
async def stage_counts(db: DbSession, user: CurrentUser):
    """Сколько техники на каждом этапе — для бейджей на доске."""
    scope = []
    if _is_master_only(user):
        scope.append(_master_scope(user.id))
    counts: dict[str, int] = {}
    for key, statuses in STAGE_STATUSES.items():
        cnt = (
            await db.execute(
                select(func.count())
                .select_from(
                    select(Repair)
                    .where(Repair.status.in_(statuses), *scope)
                    .subquery()
                )
            )
        ).scalar() or 0
        counts[key] = cnt
    counts["all"] = (
        await db.execute(
            select(func.count())
            .select_from(select(Repair).where(*scope).subquery())
        )
    ).scalar() or 0
    return counts


@router.get("/by-number/{number}", response_model=RepairOut)
async def get_by_number(number: str, db: DbSession, user: CurrentUser):
    row = await db.execute(
        select(Repair)
        .where(Repair.number == number)
        .options(
            selectinload(Repair.client),
            selectinload(Repair.master),
            selectinload(Repair.events),
            selectinload(Repair.masters).selectinload(RepairMaster.user),
        )
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")
    return _serialize(repair)


@router.get("/{repair_id}", response_model=RepairOut)
async def get_repair(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")
    return _serialize(repair)


@router.patch("/{repair_id}", response_model=RepairOut)
async def update_repair(
    repair_id: uuid.UUID, payload: RepairUpdate, db: DbSession, user: CurrentUser
):
    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")

    from app.db.base import utcnow

    old_status = repair.status
    old_master_id = repair.master_id
    data = payload.model_dump(exclude_unset=True)
    master_ids = data.pop("master_ids", None)
    helper_ids = data.pop("helper_ids", None)
    # Назначение мастеров/помощников — только admin и operator (проверка на
    # сервере, не только скрытие в UI).
    if (
        master_ids is not None
        or helper_ids is not None
        or "master_id" in data
    ) and not _can_assign_masters(user):
        raise HTTPException(403, "Мастера назначает администратор или оператор")

    # Финансовые поля (цена, себестоимость, выплата мастерам, «оплачено») —
    # только старшие роли. Иначе мастер, ведущий ремонт, может сам назначить
    # себе выплату и завысить цену.
    touched_financials = [f for f in FINANCIAL_FIELDS if f in data]
    if touched_financials and not can_edit_finances(user):
        raise HTTPException(
            403,
            "Цену, расходы и выплату указывает администратор, менеджер или оператор",
        )

    # Статус — только из настраиваемого списка. Произвольная строка ломала
    # доску (STAGE_STATUSES), очередь call-центра и статистику: все они
    # фильтруют по точному совпадению, и ремонт становился невидимым.
    if data.get("status") is not None:
        allowed = await get_repair_statuses(db)
        if data["status"] not in allowed:
            raise HTTPException(
                422,
                f"Недопустимый статус. Доступные: {', '.join(allowed)}",
            )

    for field, value in data.items():
        setattr(repair, field, value)

    # Каких мастеров назначили заново в этом запросе (чтобы уведомить в личку).
    newly_assigned_ids: list[uuid.UUID] = []

    # Несколько мастеров на один ремонт: перезаписываем список целиком.
    if master_ids is not None:
        # убрать дубликаты, сохранив порядок
        ordered_ids: list[uuid.UUID] = []
        for mid in master_ids:
            if mid not in ordered_ids:
                ordered_ids.append(mid)

        if ordered_ids:
            rows = await db.execute(select(User).where(User.id.in_(ordered_ids)))
            found = {u.id for u in rows.scalars().all()}
            missing = [str(m) for m in ordered_ids if m not in found]
            if missing:
                raise HTTPException(404, f"Мастер не найден: {', '.join(missing)}")

        old_count = len(repair.masters)
        # Обновляем список «по-разному»: существующие связи переиспользуем,
        # иначе DELETE+INSERT той же пары в одном flush ломает уникальный индекс.
        existing = {m.user_id: m for m in repair.masters}
        already = set(existing) | ({repair.master_id} if repair.master_id else set())
        newly_assigned_ids = [mid for mid in ordered_ids if mid not in already]
        for link in list(repair.masters):
            if link.user_id not in ordered_ids:
                repair.masters.remove(link)
        for position, mid in enumerate(ordered_ids):
            link = existing.get(mid)
            if link is not None:
                link.position = position
            else:
                repair.masters.append(RepairMaster(user_id=mid, position=position))
        # Основной мастер = первый в списке (используется правами и доской).
        if "master_id" not in data:
            repair.master_id = ordered_ids[0] if ordered_ids else None

        if len(ordered_ids) != old_count or ordered_ids:
            repair.events.append(
                RepairEvent(
                    repair_id=repair.id,
                    type="assign",
                    actor_id=user.id,
                    data={"message": "Изменён состав мастеров", "count": len(ordered_ids)},
                )
            )
    elif "master_id" in data and data["master_id"]:
        # Одиночное назначение — держим список мастеров в согласованном виде.
        if (
            data["master_id"] != repair.master_id
            and not any(m.user_id == data["master_id"] for m in repair.masters)
        ):
            repair.masters.append(
                RepairMaster(user_id=data["master_id"], position=len(repair.masters))
            )
            newly_assigned_ids.append(data["master_id"])

    # Помощники мастера (в бланке — «Inžiner (kömekçi)»). Хранятся в той же
    # таблице repair_masters с kind="helper", чтобы не плодить лишние сущности.
    if helper_ids is not None:
        ordered_helper_ids: list[uuid.UUID] = []
        for hid in helper_ids:
            if hid not in ordered_helper_ids:
                ordered_helper_ids.append(hid)

        if ordered_helper_ids:
            rows = await db.execute(select(User).where(User.id.in_(ordered_helper_ids)))
            found = {u.id for u in rows.scalars().all()}
            missing = [str(h) for h in ordered_helper_ids if h not in found]
            if missing:
                raise HTTPException(404, f"Помощник не найден: {', '.join(missing)}")

        existing_helpers = {
            m.user_id: m for m in repair.masters if (m.kind or "master") == "helper"
        }
        new_helper_ids = [
            hid for hid in ordered_helper_ids if hid not in existing_helpers
        ]
        for link in list(repair.masters):
            if (link.kind or "master") == "helper" and link.user_id not in ordered_helper_ids:
                repair.masters.remove(link)
        base_position = len(
            [m for m in repair.masters if (m.kind or "master") != "helper"]
        )
        for offset, hid in enumerate(ordered_helper_ids):
            link = existing_helpers.get(hid)
            if link is None:
                repair.masters.append(
                    RepairMaster(
                        user_id=hid,
                        position=base_position + offset,
                        kind="helper",
                    )
                )
        if new_helper_ids:
            newly_assigned_ids.extend(new_helper_ids)
            repair.events.append(
                RepairEvent(
                    repair_id=repair.id,
                    type="assign",
                    actor_id=user.id,
                    data={
                        "message": "Назначен помощник мастера",
                        "count": len(ordered_helper_ids),
                    },
                )
            )

    # Как только у ремонта появился основной мастер — он сам начинает работу,
    # поэтому «Принято» автоматически переходит в «Диагностика» (если статус
    # не задан явно в этом же запросе и мастер назначается впервые).
    had_master_before = bool(old_master_id)
    if (
        payload.status is None
        and old_status == "Принято"
        and repair.master_id
        and not had_master_before
    ):
        repair.status = "Диагностика"

    if repair.status != old_status:
        repair.events.append(
            RepairEvent(
                repair_id=repair.id,
                type="status_change",
                actor_id=user.id,
                data={"from": old_status, "to": repair.status},
            )
        )
        if repair.status == "Готово к выдаче":
            repair.ready_at = utcnow()
        if repair.status == "Выдано":
            repair.issued_at = utcnow()

    # Финализация починки: оператор указал расходы/цену/оплату.
    if payload.cost_amount is not None or payload.price_final is not None:
        repair.events.append(
            RepairEvent(
                repair_id=repair.id,
                type="price",
                actor_id=user.id,
                data={
                    "message": "Оформлена починка",
                    "cost_amount": payload.cost_amount,
                    "price_final": payload.price_final,
                },
            )
        )
    if payload.paid is True and not repair.paid:
        repair.events.append(
            RepairEvent(
                repair_id=repair.id,
                type="price",
                actor_id=user.id,
                data={"message": "Отмечено как оплаченное"},
            )
        )

    # Аудит значимых изменений (деньги, статус, назначение).
    if repair.status != old_status:
        await audit.record(
            db,
            audit.ACTION_REPAIR_STATUS,
            actor_id=user.id,
            entity="repair",
            entity_id=repair.id,
            meta={"from": old_status, "to": repair.status, "number": repair.number},
        )
    if touched_financials:
        await audit.record(
            db,
            audit.ACTION_REPAIR_FINANCE,
            actor_id=user.id,
            entity="repair",
            entity_id=repair.id,
            meta={
                "number": repair.number,
                "fields": {f: _num(getattr(repair, f, None)) for f in touched_financials},
            },
        )
    if newly_assigned_ids:
        await audit.record(
            db,
            audit.ACTION_REPAIR_ASSIGN,
            actor_id=user.id,
            entity="repair",
            entity_id=repair.id,
            meta={
                "number": repair.number,
                "assigned": [str(x) for x in newly_assigned_ids],
            },
        )

    await db.commit()
    # Сессия живёт с expire_on_commit=False, поэтому связи (master, masters)
    # остались бы прежними — сбрасываем кэш, чтобы ответ был актуальным.
    db.expire(repair)  # после expire нельзя трогать repair.* — берём id из пути
    repair = await _get_repair_or_404(db, repair_id)

    # Уведомляем в личку + авто-SMS мастерам, назначенным в этом запросе.
    # В личку сообщаем, только если назначил кто-то другой (не сам мастер) и
    # это сделал оператор/менеджер/админ. А вот SMS на телефон мастера (если
    # указан в его профиле) уходит всегда — даже если мастер назначил себя сам.
    if newly_assigned_ids:
        rows = await db.execute(select(User).where(User.id.in_(newly_assigned_ids)))
        for master in rows.scalars().all():
            if master.id != user.id and _is_assigner(user):
                await send_assignment_notice(
                    db, actor=user, master=master, repair=repair
                )
            await send_master_assignment_sms(master, repair, db=db)

    if repair.status != old_status:
        await manager.broadcast(
            {
                "type": "repair.status_changed",
                "repair": {"number": repair.number, "status": repair.status},
            }
        )
    return _serialize(repair)


# Кнопка «Ремонт закончен» доступна админу и оператору
# (см. app.core.permissions.FINISH_ROLES).
# Статусы, «после» готовности — назад в «Готово к выдаче» не переводим.
_FINISH_TERMINAL = {"Выдано", "Не забрано", "Архив", "Отказ"}


def _require_finisher(user) -> None:
    if not can_finish_repair(user):
        raise HTTPException(403, "Только админ или оператор")


class ReadySmsSend(BaseModel):
    text: str = Field(min_length=1, max_length=480)


@router.post("/{repair_id}/finish")
async def finish_repair(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """«Ремонт закончен»: переводит в «Готово к выдаче» и возвращает шаблон SMS клиенту.

    Отправка SMS — по желанию (следующим запросом /finish-sms или пропустить).
    """
    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")
    _require_finisher(user)

    from app.db.base import utcnow

    old_status = repair.status
    if repair.status != "Готово к выдаче" and repair.status not in _FINISH_TERMINAL:
        repair.status = "Готово к выдаче"
        repair.ready_at = utcnow()
        repair.events.append(
            RepairEvent(
                repair_id=repair.id,
                type="status_change",
                actor_id=user.id,
                data={"from": old_status, "to": "Готово к выдаче"},
            )
        )
        await db.commit()
        db.expire(repair)
        repair = await _get_repair_or_404(db, repair_id)
        await manager.broadcast(
            {
                "type": "repair.status_changed",
                "repair": {"number": repair.number, "status": "Готово к выдаче"},
            }
        )

    from app.services.settings import get_sms_templates

    tpl = await get_sms_templates(db)
    text = build_ready_sms(repair, template=tpl.get("ready") or None)
    return {
        "repair": _serialize(repair),
        "sms": {"to": repair.client.phone, "text": text},
    }


@router.post("/{repair_id}/finish-sms")
async def finish_repair_send_sms(
    repair_id: uuid.UUID,
    payload: ReadySmsSend,
    db: DbSession,
    user: CurrentUser,
):
    """Отправить клиенту SMS (текст по шаблону или свой) о готовности ремонта."""
    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")
    _require_finisher(user)

    result = await send_sms(repair.client.phone, payload.text, db=db)
    if not result.get("ok"):
        raise HTTPException(
            502, f"Не удалось отправить SMS: {result.get('detail', 'ошибка шлюза')}"
        )

    repair.events.append(
        RepairEvent(
            repair_id=repair.id,
            type="notify",
            actor_id=user.id,
            data={"message": "Клиенту отправлено SMS о готовности ремонта"},
        )
    )
    await db.commit()
    return {"ok": True, "to": repair.client.phone}


@router.post("/{repair_id}/events", response_model=RepairOut)
async def add_event(
    repair_id: uuid.UUID, db: DbSession, user: CurrentUser, comment: dict
):
    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")
    repair.events.append(
        RepairEvent(
            repair_id=repair.id,
            type="comment",
            actor_id=user.id,
            data={"message": comment.get("message", "")},
        )
    )
    await db.commit()
    return _serialize(await _get_repair_or_404(db, repair_id))


# --------------------------------------------------------------------------
# Заказанные под ремонт запчасти (в бланке — «Sargalan gerek bolan
# ätiýaçlyk şaýlary»). Свободный текст: заказывают и то, чего нет в каталоге.
# --------------------------------------------------------------------------
@router.get("/{repair_id}/part-orders", response_model=list[PartOrderOut])
async def list_part_orders(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")
    rows = await db.execute(
        select(RepairPartOrder)
        .where(RepairPartOrder.repair_id == repair_id)
        .order_by(RepairPartOrder.created_at)
    )
    return list(rows.scalars().all())


@router.post("/{repair_id}/part-orders", response_model=PartOrderOut, status_code=201)
async def add_part_order(
    repair_id: uuid.UUID, payload: PartOrderCreate, db: DbSession, user: CurrentUser
):
    from app.db.base import utcnow

    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")

    order = RepairPartOrder(
        repair_id=repair_id,
        name=payload.name.strip(),
        qty=payload.qty,
        ordered_at=payload.ordered_at or utcnow(),
        price=payload.price,
        created_by=user.id,
    )
    db.add(order)
    db.add(
        RepairEvent(
            repair_id=repair_id,
            type="comment",
            actor_id=user.id,
            data={"message": f"Заказана запчасть: {order.name} ×{order.qty}"},
        )
    )
    await db.commit()
    await db.refresh(order)
    return order


@router.patch("/{repair_id}/part-orders/{order_id}", response_model=PartOrderOut)
async def update_part_order(
    repair_id: uuid.UUID,
    order_id: uuid.UUID,
    payload: PartOrderUpdate,
    db: DbSession,
    user: CurrentUser,
):
    order = await db.get(RepairPartOrder, order_id)
    if order is None or order.repair_id != repair_id:
        raise HTTPException(404, "Заказ запчасти не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    await db.commit()
    await db.refresh(order)
    return order


@router.delete("/{repair_id}/part-orders/{order_id}")
async def delete_part_order(
    repair_id: uuid.UUID, order_id: uuid.UUID, db: DbSession, user: CurrentUser
):
    order = await db.get(RepairPartOrder, order_id)
    if order is None or order.repair_id != repair_id:
        raise HTTPException(404, "Заказ запчасти не найден")
    await db.delete(order)
    await db.commit()
    return {"ok": True}


@router.get("/{repair_id}/photos", response_model=list[PhotoOut])
async def list_photos(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")
    row = await db.execute(
        select(RepairPhoto)
        .where(RepairPhoto.repair_id == repair_id)
        .order_by(RepairPhoto.created_at)
    )
    return [
        PhotoOut(
            id=p.id,
            repair_id=p.repair_id,
            caption=p.caption,
            created_at=p.created_at,
            url=public_url(p.object_key),
        )
        for p in row.scalars().all()
    ]


@router.post("/{repair_id}/photos", response_model=PhotoOut, status_code=201)
async def upload_photo(
    repair_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
):
    repair = await _get_repair_or_404(db, repair_id)
    if not _can_access(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:  # 20 MB cap
        raise HTTPException(413, "Файл слишком большой (макс. 20 МБ)")

    try:
        object_key = object_key_for(str(repair.id), file.filename or "photo.jpg")
    except ValueError as e:
        raise HTTPException(400, str(e))

    await save_object(data, object_key)

    photo = RepairPhoto(
        repair_id=repair.id,
        object_key=object_key,
        caption=caption,
        uploaded_by=user.id,
    )
    db.add(photo)
    repair.events.append(
        RepairEvent(
            repair_id=repair.id,
            type="photo",
            actor_id=user.id,
            data={"photo_id": str(photo.id)},
        )
    )
    await db.commit()
    await db.refresh(photo)

    return PhotoOut(
        id=photo.id,
        repair_id=photo.repair_id,
        caption=photo.caption,
        created_at=photo.created_at,
        url=public_url(photo.object_key),
    )
