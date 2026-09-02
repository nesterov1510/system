import uuid
from datetime import timedelta

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
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
from app.services.chat import send_assignment_notice
from app.services.numbering import next_repair_number, new_public_token, normalize_phone
from app.services.sms import (
    build_ready_sms,
    send_master_assignment_sms,
    send_sms,
)
from app.services.settings import get_storage_months
from app.services.storage import object_key_for, public_url, save_object
from app.ws.manager import manager

router = APIRouter(prefix="/repairs", tags=["repairs"])


def _can_access(user, repair: Repair) -> bool:
    """Masters see only their own repairs; others see all."""
    if user.role == UserRole.MASTER.value:
        if repair.master_id == user.id:
            return True
        # Ремонт могут вести несколько мастеров — доступ есть у каждого из них.
        return any(m.user_id == user.id for m in repair.masters)
    return True


def _is_assigner(user) -> bool:
    """Кто может назначать мастеров на ремонт (не сам мастер)."""
    return user.role in (
        UserRole.ADMIN.value,
        UserRole.MANAGER.value,
        UserRole.OPERATOR.value,
    )


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
    masters = list(repair.masters)
    master_ids = [m.user_id for m in masters]
    master_names = [m.user.name for m in masters if m.user]
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
        client_name=repair.client.full_name,
        client_phone=repair.client.phone,
        master_name=repair.master.name if repair.master else None,
        master_ids=master_ids,
        master_names=master_names,
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
    if user.role == UserRole.MASTER.value:
        repairs_q = repairs_q.where(_master_scope(user.id))
    r = await db.execute(repairs_q)
    return [_serialize(x) for x in r.scalars().all()]



def _require_admin(user) -> None:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "Только администратор")


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: uuid.UUID, db: DbSession, user: CurrentUser
):
    """Удалить клиента (мягкое удаление) — только админ."""
    _require_admin(user)
    from app.db.base import utcnow

    row = await db.execute(select(Client).where(Client.id == client_id))
    client = row.scalar_one_or_none()
    if client is None or client.deleted_at is not None:
        raise HTTPException(404, "Клиент не найден")
    client.deleted_at = utcnow()
    await db.commit()
    return {"ok": True}


@router.delete("/{repair_id}")
async def delete_repair(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Полное удаление ремонта со всеми зависимостями — только админ."""
    _require_admin(user)
    repair = await db.get(Repair, repair_id)
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
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
    await db.commit()
    await manager.broadcast({"type": "repair.deleted", "repair": {"id": str(repair_id)}})
    return {"ok": True}


@router.post("", response_model=RepairOut, status_code=201)
async def create_repair(
    payload: RepairCreate,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    # Idempotency: repeated submit with same key returns the existing repair.
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

    # Upsert client by normalized phone.
    phone_norm = normalize_phone(payload.client.phone)
    row = await db.execute(select(Client).where(Client.phone_norm == phone_norm))
    client = row.scalar_one_or_none()
    if client is None:
        client = Client(
            full_name=payload.client.full_name,
            phone=payload.client.phone,
            phone_norm=phone_norm,
        )
        db.add(client)
        await db.flush()
    else:
        client.full_name = payload.client.full_name

    from app.db.base import utcnow

    number = await next_repair_number(db, city, payload.device_type)
    storage_months = await get_storage_months(db)
    now = utcnow()

    # Если приёмку ведёт мастер — он автоматически назначается исполнителем.
    master_id = payload.master_id
    if master_id is None and user.role == UserRole.MASTER.value:
        master_id = user.id

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
        consent_repair_at=now if payload.consent_repair else None,
        accepted_by=user.id,
        master_id=master_id,
        status="Принято",
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
    await db.commit()

    repair = await _get_repair_or_404(db, repair.id)

    # Если оператор/админ при приёмке сразу назначил мастера — сообщим ему в личку
    # и отправим авто-SMS (если у мастера указан номер).
    if (
        master_id
        and _is_assigner(user)
        and repair.master is not None
        and repair.master.id != user.id
    ):
        await send_assignment_notice(db, actor=user, master=repair.master, repair=repair)
        await send_master_assignment_sms(repair.master, repair)

    # Notify the chat: new acceptance.
    await manager.broadcast(
        {
            "type": "repair.created",
            "repair": {"number": repair.number, "status": repair.status},
        }
    )
    return _serialize(repair)


# Группы-этапы для страницы «Все ремонты» (вкладки).
STAGE_STATUSES: dict[str, list[str]] = {
    "new": ["Принято"],
    "diag": ["Диагностика"],
    "work": ["Согласование", "Ожидание запчастей", "В ремонте"],
    "done": ["Готово к выдаче", "Выдано", "Не забрано", "Архив", "Отказ"],
}


@router.get("", response_model=RepairsPage)
async def list_repairs(
    db: DbSession,
    user: CurrentUser,
    stage: str | None = Query(
        None, pattern="^(new|diag|work|done|all)$", description="Фильтр по этапу"
    ),
    status: str | None = None,
    master_id: uuid.UUID | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    from sqlalchemy import or_

    filters = []
    if stage and stage != "all" and stage in STAGE_STATUSES:
        filters.append(Repair.status.in_(STAGE_STATUSES[stage]))
    if status:
        filters.append(Repair.status == status)
    if master_id:
        filters.append(Repair.master_id == master_id)
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
    if user.role == UserRole.MASTER.value:
        filters.append(_master_scope(user.id))

    base = select(Repair).where(*filters)

    total_row = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_row.scalar() or 0

    q_stmt = (
        base.options(
            selectinload(Repair.client),
            selectinload(Repair.master),
            selectinload(Repair.events),
            selectinload(Repair.masters).selectinload(RepairMaster.user),
        )
        .order_by(Repair.accepted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    row = await db.execute(q_stmt)
    items = [_serialize(r) for r in row.scalars().all()]
    return RepairsPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/stage-counts")
async def stage_counts(db: DbSession, user: CurrentUser):
    """Сколько техники на каждом этапе — для бейджей на доске."""
    scope = []
    if user.role == UserRole.MASTER.value:
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
    data = payload.model_dump(exclude_unset=True)
    master_ids = data.pop("master_ids", None)
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

    if payload.status and payload.status != old_status:
        repair.events.append(
            RepairEvent(
                repair_id=repair.id,
                type="status_change",
                actor_id=user.id,
                data={"from": old_status, "to": payload.status},
            )
        )
        if payload.status == "Готово к выдаче":
            repair.ready_at = utcnow()
        if payload.status == "Выдано":
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

    await db.commit()
    # Сессия живёт с expire_on_commit=False, поэтому связи (master, masters)
    # остались бы прежними — сбрасываем кэш, чтобы ответ был актуальным.
    db.expire(repair)  # после expire нельзя трогать repair.* — берём id из пути
    repair = await _get_repair_or_404(db, repair_id)

    # Уведомляем в личку + авто-SMS мастерам, назначенным в этом запросе.
    if newly_assigned_ids and _is_assigner(user):
        rows = await db.execute(select(User).where(User.id.in_(newly_assigned_ids)))
        for master in rows.scalars().all():
            if master.id != user.id:
                await send_assignment_notice(
                    db, actor=user, master=master, repair=repair
                )
                await send_master_assignment_sms(master, repair)

    if payload.status and payload.status != old_status:
        await manager.broadcast(
            {
                "type": "repair.status_changed",
                "repair": {"number": repair.number, "status": payload.status},
            }
        )
    return _serialize(repair)


# Кнопка «Ремонт закончен» доступна админу и оператору.
_FINISH_ROLES = (UserRole.ADMIN.value, UserRole.OPERATOR.value)
# Статусы, «после» готовности — назад в «Готово к выдаче» не переводим.
_FINISH_TERMINAL = {"Выдано", "Не забрано", "Архив", "Отказ"}


def _require_finisher(user) -> None:
    if user.role not in _FINISH_ROLES:
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

    text = build_ready_sms(repair)
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

    result = await send_sms(repair.client.phone, payload.text)
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
