"""Серверные страницы: список/доска ремонтов, приёмка, карточка ремонта.

Мутации (создание/обновление ремонта, запчасти, платежи, события, печать)
вызывают те же функции, что и JSON-API, — бизнес-логика не дублируется.
"""
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.core.permissions import (
    can_access_repair,
    can_add_repair_part,
    can_assign_masters,
    can_assign_repair_masters,
    can_delete_repair,
    can_edit_device_info,
    can_edit_finances,
    can_finish_repair,
    can_print,
    can_refund_payment,
    can_set_repair_part_price,
    can_take_payment,
    can_view_repair,
    is_master_only,
)
from app.db.models import (
    Client,
    ComplectationItem,
    Payment,
    Repair,
    RepairMaster,
    RepairPart,
    RepairPhoto,
    User,
    UserRole,
)
from app.db.session import async_session_factory
from app.routers import parts as parts_api
from app.routers import payments as payments_api
from app.routers import prints as prints_api
from app.routers import repairs as repairs_api
from app.schemas.parts import RepairPartAdd
from app.schemas.payments import PaymentCreate
from app.schemas.repair import ClientCreate, RepairCreate, RepairUpdate
from app.services.settings import get_currency, get_repair_statuses
from app.services.numbering import (
    DEFAULT_COUNTRY_CODE,
    phone_digits,
    validate_tm_phone,
)
from app.webui.catalog import CONDITION_OPTIONS, DEFAULT_COMPLECTATION, DEVICE_CLASSES, normalize_class
from app.webui.deps import bound_user, get_web_user
from app.webui.helpers import base_context
from app.webui.layout import (
    as_orders,
    block_keys,
    block_labels,
    get_layout,
    get_layout_order,
)

def _layout_next(request: Request) -> str:
    """Адрес возврата после сохранения раскладки (тот же экран с фильтрами)."""
    q = request.url.query
    return f"{request.url.path}?{q}" if q else request.url.path


from app.webui.templating import render_async

router = APIRouter(tags=["webui-repairs"])

# Действия из меню мастера в карточке ремонта (POST /repairs/{id}/master-action).
MASTER_ACTIONS = ("transfer", "master", "helper", "remove")


def _db():
    return async_session_factory()


async def _require(request):
    """Вернуть (db, user) или RedirectResponse на логин.

    Пользователь перечитывается в рабочей сессии (bound_user): detached-объект
    из cookie-загрузки нельзя использовать для ORM-записей.
    """
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return None, None, RedirectResponse("/login", status_code=303)
    db = _db()
    user = await bound_user(db, webuser)
    if user is None:
        await db.close()
        return None, None, RedirectResponse("/login", status_code=303)
    return db, user, None


async def _masters_list(db):
    rows = (await db.execute(select(User).where(User.active.is_(True)).order_by(User.name))).scalars().all()
    return [u for u in rows if u.has_role(UserRole.MASTER.value)]


async def _complectation(db):
    return (await db.execute(select(ComplectationItem).order_by(ComplectationItem.sort))).scalars().all()


def _checked_marks(form) -> list[str]:
    """Отмеченные пункты списка + свой текст, без дублей и пустых строк."""
    items = [(x or "").strip() for x in form.getlist("items")]
    items.append((form.get("extra") or "").strip())
    return list(dict.fromkeys(x for x in items if x))


def _join_marks(form) -> str | None:
    marks = _checked_marks(form)
    return ", ".join(marks) if marks else None


async def _cities(db):
    from app.db.models import City
    return (await db.execute(select(City).order_by(City.name))).scalars().all()


# --------------------------------------------------------------------------
# Список / доска ремонтов
# --------------------------------------------------------------------------
# Размеры страницы, доступные в селекторе «на странице» вкладки «Все ремонты».
PER_PAGE_OPTIONS = (20, 50, 100, 200)
DEFAULT_PER_PAGE = 50
# Доска не пейджится: на ней только «живые» ремонты.
BOARD_LIMIT = 300


@router.get("/repairs", response_class=HTMLResponse)
async def repairs_list(request: Request, stage: str | None = None, q: str | None = None,
                       status: str | None = None, view: str = "table", page: int = 1,
                       per_page: int = DEFAULT_PER_PAGE,
                       just: str | None = None, printed: str | None = None,
                       filter: str | None = None, hl: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from app.services.stats import DASHBOARD_FILTER_LABELS
        from app.webui.data import (
            EXTRA_STATUS_FILTERS,
            STAGE_STATUSES,
            fetch_repairs,
            repair_parts_cost,
            repair_parts_lines,
            repair_parts_names,
            repair_payments_total,
        )
        per_page = per_page if per_page in PER_PAGE_OPTIONS else DEFAULT_PER_PAGE
        page = max(int(page or 1), 1)

        if view == "board":
            # Доска: только незавершённые ремонты, без фильтров этапов/статусов
            # и панели — все подряд по приёмке от новых к старым.
            repairs, total = await fetch_repairs(
                db, user, q=q, page=1, page_size=BOARD_LIMIT,
                exclude_statuses=STAGE_STATUSES["done"],
            )
            pages = 1
        else:
            repairs, total = await fetch_repairs(
                db, user, stage=stage, status=status, q=q, page=page,
                page_size=per_page, dash_filter=filter,
            )
            pages = max(1, (total + per_page - 1) // per_page)
            if page > pages:
                page = pages
                repairs, total = await fetch_repairs(
                    db, user, stage=stage, status=status, q=q, page=page,
                    page_size=per_page, dash_filter=filter,
                )
        ids = [r.id for r in repairs]
        parts_cost = await repair_parts_cost(db, ids)
        parts_lines = await repair_parts_lines(db, ids)
        parts_names = await repair_parts_names(db, ids)
        pays = await repair_payments_total(db, ids)
        currency = await get_currency(db)
        statuses = await get_repair_statuses(db)
        masters = await _masters_list(db)
        master_only = is_master_only(user)
        # Мастер видит все ремонты и может брать свободные себе — поэтому
        # колонка «Мастера» редактируется и ему, а не только старшим ролям.
        can_assign_ui = can_assign_masters(user) or master_only
        # Конструктор блоков страницы — только админу, порядок личный.
        can_layout = user.has_role("admin")
        layout = await get_layout(db, user.id, "repairs_list") if can_layout else \
            as_orders("repairs_list", None)
        # Порядок колонок таблицы — тоже личный (page="repairs_columns").
        layout_cols = await get_layout_order(db, user.id, "repairs_columns") if can_layout \
            else block_keys("repairs_columns")
        ctx = await base_context(
            request, await get_web_user(request), active="/repairs",
            repairs=repairs, total=total, stage=stage or "all", q=q or "",
            status=status, view=view, page=page, pages=pages,
            per_page=per_page, per_page_options=PER_PAGE_OPTIONS,
            parts_cost=parts_cost,
            parts_names=parts_names, parts_lines=parts_lines, pays=pays, currency=currency,
            statuses=statuses, masters=masters,
            extra_status_filters=EXTRA_STATUS_FILTERS,
            layout=layout,
            layout_labels=block_labels("repairs_list"),
            layout_default=block_keys("repairs_list"),
            layout_page="repairs_list",
            layout_next=_layout_next(request),
            layout_cols_order=",".join(layout_cols),
            layout_cols_default=block_keys("repairs_columns"),
            can_layout=can_layout,
            masters_json=[{"id": str(m.id), "name": m.name} for m in masters],
            just=just, printed=printed,
            sms=request.query_params.get("sms"),
            sms_detail=request.query_params.get("sms_detail"),
            can_finish=can_finish_repair(user),
            # Выдачу техники клиенту отмечает тот, кто закрывает ремонт.
            can_issue=can_finish_repair(user),
            can_print_any=not master_only,
            can_delete=can_delete_repair(user),
            # Инлайн-редактирование ячеек в таблице (двойной клик) — для
            # старших ролей; мастеру список только на чтение + меню действий.
            can_inline=not master_only,
            can_finance=can_edit_finances(user),
            can_device=can_edit_device_info(user),
            can_assign=can_assign_ui,
            can_client=user.has_role("admin", "manager", "operator"),
            me_id=str(user.id),
            # Кнопка «Готово, но всё ещё в сервисе»: подсветка ремонтов,
            # которые завершены, а клиент технику не забрал.
            hl_ready=(hl == "ready"),
            dash_filter=filter or "",
            dash_filter_label=DASHBOARD_FILTER_LABELS.get(filter or ""),
        )
        html = await render_async(
            "repairs/list.html" if view == "table" else "repairs/board.html"
        , **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/repairs/bulk-delete")
async def repairs_bulk_delete(request: Request):
    """Админ отмечает ремонты в списке и удаляет выбранные."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        if not can_delete_repair(user):
            return HTMLResponse("Только администратор", status_code=403)
        form = await request.form()
        deleted = 0
        for raw in form.getlist("ids")[:80]:
            try:
                rid = uuid.UUID(str(raw))
            except ValueError:
                continue
            try:
                await repairs_api.delete_repair(rid, db, user)
                deleted += 1
            except HTTPException:
                continue
        return RedirectResponse(f"/repairs?just=deleted&n={deleted}", status_code=303)
    finally:
        await db.close()


# --------------------------------------------------------------------------
# Приёмка
# --------------------------------------------------------------------------
@router.get("/repairs/new", response_class=HTMLResponse)
async def repair_new_form(request: Request, type: str | None = None):
    db, _user, redir = await _require(request)
    if redir:
        return redir
    try:
        sel = normalize_class(type) if type else None
        # Администратор/оператор выбирают любого мастера. Мастер на приёмке
        # может назначить только себя либо оставить поле пустым (ремонт уйдёт
        # в общую очередь, и его возьмёт свободный мастер).
        can_assign = can_assign_masters(_user)
        can_self_assign = is_master_only(_user)
        if can_assign:
            masters = await _masters_list(db)
        elif can_self_assign:
            masters = [_user]
        else:
            masters = []
        ctx = await base_context(
            request, await get_web_user(request), active="/repairs/new",
            cities=await _cities(db),
            masters=masters,
            complectation=await _complectation(db), device_classes=DEVICE_CLASSES,
            brands=[], error=None, form={}, sel_type=sel,
            can_assign=can_assign, can_self_assign=can_self_assign,
        )
        html = await render_async("repairs/new.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.get("/web/clients-suggest")
async def clients_suggest(request: Request, q: str = ""):
    """Автокомплит заказчика в приёмке: поиск клиента по телефону или имени.

    Доступен любому авторизованному сотруднику, который открывает приёмку.
    """
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    q = (q or "").strip()
    if len(q) < 2:
        return []
    db = _db()
    try:
        digits = "".join(ch for ch in q if ch.isdigit())
        like_txt = f"%{q}%"
        conds = [Client.full_name.ilike(like_txt), Client.phone.ilike(like_txt)]
        if len(digits) >= 3:
            conds.append(Client.phone_norm.contains(digits))
        rows = (
            await db.execute(
                select(Client)
                .where(Client.deleted_at.is_(None), or_(*conds))
                .order_by(Client.full_name)
                .limit(8)
            )
        ).scalars().all()
        return [{"name": c.full_name, "phone": c.phone} for c in rows]
    finally:
        await db.close()


@router.post("/repairs/new")
async def repair_create(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        # Номер телефона: +993 + код оператора (12, 60–65, 71, 72) + 6 цифр.
        # На форме это проверяет priemka/phone.js, но форму можно отправить и
        # в обход скрипта — поэтому проверка повторяется здесь.
        phone_err = validate_tm_phone(form.get("phone", ""))
        if phone_err:
            raise ValueError(f"Номер телефона заказчика: {phone_err}")
        contact2_raw = (form.get("contact2_phone") or "").strip()
        if phone_digits(contact2_raw) not in ("", DEFAULT_COUNTRY_CODE):
            contact2_err = validate_tm_phone(contact2_raw)
            if contact2_err:
                raise ValueError(f"Телефон дополнительного контакта: {contact2_err}")
        comp = {}
        async for key in _iter_comp(form):
            comp[key] = True
        # Комплектация по форме эталона: чекбоксы equipment[] + «другое».
        _EQUIP_LABELS = {
            "remote": "Пульт", "power_cable": "Шнур питания", "legs": "Ножки",
            "wall_mount": "Настенное крепление", "box_ir_eye": "Глазок/ИК-приёмник",
            "box": "Коробка", "all_in_box": "Всё в комплекте в коробке",
        }
        for val in form.getlist("equipment"):
            comp[_EQUIP_LABELS.get(val, val)] = True
        equip_other = (form.get("equipment_other") or "").strip()
        if equip_other:
            for item in equip_other.split(","):
                item = item.strip()
                if item:
                    comp[item] = True
        # Кастомные позиции комплектации (старый чек-блок из справочника).
        custom = (form.get("complectation_custom") or "").strip()
        if custom:
            for item in custom.split(","):
                item = item.strip()
                if item:
                    comp[item] = True

        # Внешнее состояние: предустановленные отметки + свободный текст.
        _COND_LABELS = {
            "screen_scratches": "Царапины на экране",
            "body_scratches": "Царапины на корпусе",
            "broken_parts": "Есть сломанные места",
            "other_service": "Был в другом сервисе",
        }
        cond_parts = [
            _COND_LABELS[v] for v in form.getlist("condition") if v in _COND_LABELS
        ]
        condition_other = (form.get("condition_other") or "").strip()
        if condition_other:
            cond_parts.append(condition_other)
        condition_notes = "; ".join(cond_parts) or None

        # Кнопка «Доставка» присылает "1"/"0"; bool("0") дал бы True, и каждый
        # заказ считался бы привезённым с доставкой.
        is_delivery = (form.get("is_delivery") or "").strip() in ("1", "true", "on")
        delivery_district = (form.get("delivery_district") or "").strip() or None
        delivery_comment = (form.get("delivery_comment") or "").strip() or None
        if not is_delivery:
            delivery_district = None
            delivery_comment = None
        brand = _caps_ident(form.get("brand_manual") or form.get("brand"))
        model = _caps_ident(form.get("model_manual") or form.get("model"))
        serial = _caps_ident(form.get("serial_manual") or form.get("serial"))
        if not brand and not model and not serial:
            brand, model, serial = _parse_identity(form.get("identity_raw"))
        # Мастера выбирают администратор/оператор. Мастер на приёмке может
        # назначить только себя; пустое поле оставляет ремонт в очереди.
        master_id = None
        raw_master = (form.get("master_id") or "").strip()
        if raw_master:
            try:
                picked = uuid.UUID(raw_master)
            except ValueError:
                picked = None
            if can_assign_masters(user):
                master_id = picked
            elif is_master_only(user) and picked == user.id:
                master_id = picked
        payload = RepairCreate(
            city_id=uuid.UUID(form["city_id"]),
            client=ClientCreate(
                full_name=form.get("full_name", ""),
                phone=form.get("phone", ""),
                consent_pdn=bool(form.get("consent_pdn")),
                consent_storage=bool(form.get("consent_storage")),
            ),
            contact2_name=(form.get("contact2_name") or "").strip() or None,
            contact2_phone=(form.get("contact2_phone") or "").strip() or None,
            contact2_relation=(form.get("contact2_relation") or "").strip() or None,
            device_type=normalize_class(form.get("device_type") or "Другое"),
            brand=brand,
            model=model,
            serial=serial,
            complectation=comp or None,
            fault_client=(form.get("fault_client") or "").strip() or None,
            condition_notes=condition_notes,
            master_id=master_id,
            consent_repair=bool(form.get("consent_repair")),
            is_delivery=is_delivery,
            delivery_district=delivery_district,
            delivery_comment=delivery_comment,
        )
        out = await repairs_api.create_repair(payload=payload, db=db, user=user, idempotency_key=None)
        rid = out.id

        # --- Фото состояния при приёмке (multipart, секция 03) ---
        try:
            from app.services.storage import object_key_for, save_object
            uploads = []
            for f in form.getlist("photos"):
                if getattr(f, "filename", ""):
                    uploads.append(f)
            cam = form.get("photo_camera")
            if getattr(cam, "filename", ""):
                uploads.append(cam)
            for f in uploads[:12]:
                data = await f.read()
                if not data:
                    continue
                key = object_key_for(str(rid), f.filename or "photo.jpg")
                await save_object(data, key)
                db.add(RepairPhoto(
                    repair_id=rid, object_key=key,
                    caption="Состояние при приёмке", uploaded_by=user.id,
                ))
            if uploads:
                await db.commit()
        except Exception:
            pass  # фото не должны ломать приёмку

        # --- Автопечать при приёмке ---
        # По умолчанию печатаются ДВЕ этикетки 58×38: одна на технику (№,
        # клиент, комплектация, QR для мастера), вторая клиенту (QR на
        # публичную страницу со статусом, условиями хранения и юр. информацией).
        # Что печатать — этикетки / бланк / всё / ничего — выбирается в админке
        # «Настройки → Печать → Автопечать при приёмке».
        label_printed = False
        try:
            from app.services import settings as settings_svc
            repair = await repairs_api._get_repair_or_404(db, rid)
            if can_print(user, repair):
                auto = await settings_svc.get_intake_auto_print(db)
                if auto in ("label", "both"):
                    await prints_api.create_label_print_job(
                        repair_id=rid, db=db, user=user, request=request
                    )
                    await prints_api.create_client_label_print_job(
                        repair_id=rid, db=db, user=user, request=request
                    )
                    label_printed = True
                if auto in ("blank", "both"):
                    await prints_api.create_print_job(
                        repair_id=rid, db=db, user=user, request=request
                    )
        except Exception:
            pass  # проблемы печати не должны ломать приёмку
        # После сохранения — сразу в список ремонтов с подтверждением.
        return RedirectResponse(
            f"/repairs?just=accepted&printed={'1' if label_printed else '0'}",
            status_code=303,
        )
    except Exception as e:
        _submitted = dict(await request.form())
        can_assign = can_assign_masters(user)
        can_self_assign = is_master_only(user)
        if can_assign:
            masters = await _masters_list(db)
        elif can_self_assign:
            masters = [user]
        else:
            masters = []
        ctx = await base_context(
            request, await get_web_user(request), active="/repairs/new",
            cities=await _cities(db),
            masters=masters,
            complectation=await _complectation(db), device_classes=DEVICE_CLASSES,
            brands=[], error=str(getattr(e, "detail", e)), form=_submitted,
            sel_type=normalize_class(_submitted.get("device_type")) if _submitted.get("device_type") else None,
            can_assign=can_assign, can_self_assign=can_self_assign,
        )
        html = await render_async("repairs/new.html", **ctx)
        return HTMLResponse(html, status_code=400)
    finally:
        await db.close()


def _caps_ident(value: str | None) -> str | None:
    """Марка / модель / SN в приёмке всегда заглавными."""
    text = (value or "").strip()
    return text.upper() or None


def _parse_identity(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """Разбор строки «МАРКА-МОДЕЛЬ-SN», как в televisions.js."""
    import re

    value = (raw or "").strip().upper()
    if not value:
        return None, None, None
    spaced = [part.strip() for part in re.split(r"\s+[-–—]\s+", value) if part.strip()]
    if len(spaced) >= 3:
        return spaced[0], spaced[1], " - ".join(spaced[2:]) or None
    compact = value.split("-")
    if len(compact) >= 3:
        return (
            compact[0].strip() or None,
            compact[1].strip() or None,
            "-".join(compact[2:]).strip() or None,
        )
    if len(compact) == 2:
        return compact[0].strip() or None, compact[1].strip() or None, None
    return value, None, None


async def _iter_comp(form):
    for key in form:
        if key.startswith("comp_"):
            yield key[5:]


# --------------------------------------------------------------------------
# Карточка ремонта
# --------------------------------------------------------------------------
async def _load_repair(db, repair_id: uuid.UUID):
    row = await db.execute(
        select(Repair).where(Repair.id == repair_id).options(
            selectinload(Repair.client),
            selectinload(Repair.master),
            selectinload(Repair.accepted_by_user),
            selectinload(Repair.events),
            selectinload(Repair.masters).selectinload(RepairMaster.user),
            selectinload(Repair.part_orders),
        )
    )
    return row.scalar_one_or_none()


@router.get("/repairs/{repair_id}", response_class=HTMLResponse)
async def repair_detail(request: Request, repair_id: uuid.UUID,
                        just: str | None = None, sms: str | None = None,
                        sms_detail: str | None = None, printed: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        repair = await _load_repair(db, repair_id)
        if repair is None:
            return HTMLResponse("Ремонт не найден", status_code=404)
        # Список показывает мастеру все ремонты, поэтому и карточку открываем:
        # свободный заказ надо посмотреть, прежде чем взять его себе.
        if not can_view_repair(user, repair):
            return HTMLResponse("Нет доступа к этому ремонту", status_code=403)

        parts = (await db.execute(
            select(RepairPart).where(RepairPart.repair_id == repair_id)
            .options(selectinload(RepairPart.part))
        )).scalars().all()
        payments = (await db.execute(
            select(Payment).where(Payment.repair_id == repair_id)
            .options(selectinload(Payment.operator)).order_by(Payment.paid_at)
        )).scalars().all()
        photos = (await db.execute(
            select(RepairPhoto).where(RepairPhoto.repair_id == repair_id)
        )).scalars().all()
        currency = await get_currency(db)
        statuses = await get_repair_statuses(db)
        masters = await _masters_list(db)

        parts_cost = sum(float(p.price or 0) * p.qty for p in parts)
        paid_total = sum(float(p.amount) for p in payments)
        master_ids = [m.user_id for m in repair.masters if (m.kind or "master") != "helper"]

        # Конструктор блоков: порядок сохраняется лично админу.
        can_layout = user.has_role("admin")
        layout = await get_layout(db, user.id, "repair_card") if can_layout else \
            as_orders("repair_card", None)

        # Списки для чипов «Состояние» и «Комплектация»: готовые отметки +
        # справочник из БД + то, что уже отмечено в этом ремонте.
        catalog_items = [c.name for c in await _complectation(db)]
        complectation_marked = [k for k, v in (repair.complectation or {}).items() if v]
        complectation_options = list(dict.fromkeys(
            DEFAULT_COMPLECTATION + catalog_items + complectation_marked
        ))
        # «Состояние» хранится строкой через запятую: известные отметки
        # подсвечиваются в списке, остальное уходит в поле «своими словами».
        note_parts = [x.strip() for x in (repair.condition_notes or "").split(",") if x.strip()]
        condition_marks = [x for x in note_parts if x in CONDITION_OPTIONS]
        condition_free = ", ".join(x for x in note_parts if x not in CONDITION_OPTIONS)

        ctx = await base_context(
            request, await get_web_user(request), active="/repairs",
            repair=repair, parts=parts, payments=payments, photos=photos,
            currency=currency, statuses=statuses, masters=masters,
            just=just, sms=sms, sms_detail=sms_detail, printed=printed,
            parts_cost=parts_cost, paid_total=paid_total,
            master_ids=master_ids,
            device_classes=DEVICE_CLASSES,
            layout=layout,
            layout_labels=block_labels("repair_card"),
            layout_default=block_keys("repair_card"),
            layout_page="repair_card",
            layout_next=_layout_next(request),
            can_layout=can_layout,
            condition_options=CONDITION_OPTIONS,
            complectation_options=complectation_options,
            complectation_marked=complectation_marked,
            condition_marks=condition_marks,
            condition_free=condition_free,
            can={
                "finance": can_edit_finances(user),
                # Назначение — по конкретному ремонту: мастер может взять
                # свободный заказ себе и добрать помощников к своему.
                "assign": can_assign_repair_masters(user, repair),
                # Менять данные чужого ремонта мастеру нельзя.
                "edit": can_access_repair(user, repair),
                "issue": can_finish_repair(user) and repair.issued_at is None,
                "finish": can_finish_repair(user),
                "print": can_print(user, repair),
                "payment": can_take_payment(user),
                "refund": can_refund_payment(user),
                "device": can_edit_device_info(user),
                "addpart": can_add_repair_part(user),
                "setpartprice": can_set_repair_part_price(user),
                "master_only": is_master_only(user),
                "admin": can_delete_repair(user),
                "delete": can_delete_repair(user),
                # Доставку (район, телефон курьера) ведут старшие роли — как
                # и данные клиента.
                "delivery": user.has_role("admin", "manager", "operator"),
            },
        )
        html = await render_async("repairs/detail.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


# --- Действия карточки (POST → редирект назад) ---

@router.post("/repairs/{repair_id}/status")
async def repair_set_status(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        payload = RepairUpdate(status=form.get("status"))
        repair = await repairs_api._get_repair_or_404(db, repair_id)
        if not can_access_repair(user, repair):
            return HTMLResponse("Нет доступа", status_code=403)
        await repairs_api.update_repair(repair_id, payload, db, user)
        return RedirectResponse(f"/repairs/{repair_id}", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/comment")
async def repair_add_comment(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        await repairs_api.add_event(repair_id, db, user, {"message": form.get("message", "")})
        return RedirectResponse(f"/repairs/{repair_id}#log", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/finance")
async def repair_finance(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()

        def num(k):
            v = (form.get(k) or "").strip().replace(",", ".")
            return float(v) if v else None

        payload = RepairUpdate(
            price_final=num("price_final"),
            cost_amount=num("cost_amount"),
            master_payout=num("master_payout"),
            paid="paid" in form,  # чекбокс: отмечен -> True, снят -> False (колонка NOT NULL)
            work_done=(form.get("work_done") or "").strip() or None,
            warranty_text=(form.get("warranty_text") or "").strip() or None,
        )
        await repairs_api.update_repair(repair_id, payload, db, user)
        return RedirectResponse(f"/repairs/{repair_id}#pay", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/field")
async def repair_patch_field(request: Request, repair_id: uuid.UUID):
    """Одно поле карточки: правка прямо в чипе, без вкладок и большой формы."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        form = await request.form()
        field = (form.get("field") or "").strip()
        raw = form.get("value")
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        repair = await repairs_api._get_repair_or_404(db, repair_id)
        if not can_access_repair(user, repair):
            return HTMLResponse("Нет доступа", status_code=403)

        text_fields = {
            "brand", "model", "serial", "fault_client", "fault_master",
            "condition_notes", "work_done", "warranty_text", "status",
        }
        if field not in text_fields | {"eta_days", "price_final", "master_payout", "paid", "client_name", "client_phone"}:
            return HTMLResponse("Неизвестное поле", status_code=400)

        try:
            if field in ("client_name", "client_phone"):
                if not user.has_role("admin", "manager", "operator"):
                    return HTMLResponse("Недостаточно прав", status_code=403)
                kwargs = {}
                text = (raw or "").strip()
                if field == "client_name":
                    kwargs["full_name"] = text
                else:
                    kwargs["phone"] = text
                await repairs_api.update_client(
                    repair.client_id, repairs_api.ClientUpdate(**kwargs), db, user,
                )
            else:
                value = None if raw is None else str(raw).strip()
                if field == "paid":
                    payload = RepairUpdate(paid=value in ("1", "true", "on", "да"))
                elif field == "eta_days":
                    payload = RepairUpdate(eta_days=int(value) if value else None)
                elif field == "price_final":
                    payload = RepairUpdate(
                        price_final=float(value.replace(",", ".")) if value else None
                    )
                elif field == "master_payout":
                    payload = RepairUpdate(
                        master_payout=float(value.replace(",", ".")) if value else None
                    )
                else:
                    payload = RepairUpdate(**{field: value or None})
                await repairs_api.update_repair(repair_id, payload, db, user)
        except (TypeError, ValueError):
            return HTMLResponse("Некорректное значение", status_code=400)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(nxt, status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/assign")
async def repair_assign(request: Request, repair_id: uuid.UUID):
    """Назначить мастеров/помощников.

    Администратор и оператор — на любой ремонт. Мастер — на свободный (берёт
    себе) или на свой (добавляет напарников и помощников).
    """
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        form = await request.form()
        ids = [uuid.UUID(x) for x in form.getlist("master_ids") if x]
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        repair = await repairs_api._get_repair_or_404(db, repair_id)
        if not can_assign_repair_masters(user, repair):
            return HTMLResponse(
                "Этот ремонт занят другим мастером", status_code=403
            )
        payload = RepairUpdate(master_ids=ids or None)
        try:
            await repairs_api.update_repair(repair_id, payload, db, user)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(nxt, status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/master-action")
async def repair_master_action(request: Request, repair_id: uuid.UUID):
    """Действие с одним мастером из карточки ремонта.

    Клик по имени мастера открывает меню: передать ремонт, назначить
    мастером, назначить помощником или убрать с ремонта. Состав исполнителей
    при этом пересобирается целиком и уходит тем же `update_repair`, что и
    обычное назначение.
    """
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        action = (form.get("action") or "").strip()
        try:
            target = uuid.UUID((form.get("user_id") or "").strip())
        except ValueError:
            return HTMLResponse("Неизвестный мастер", status_code=400)
        if action not in MASTER_ACTIONS:
            return HTMLResponse("Неизвестное действие", status_code=400)

        repair = await repairs_api._get_repair_or_404(db, repair_id)
        if not can_assign_repair_masters(user, repair):
            return HTMLResponse("Этот ремонт занят другим мастером", status_code=403)

        masters = [m.user_id for m in repair.masters if (m.kind or "master") != "helper"]
        helpers = [m.user_id for m in repair.masters if (m.kind or "master") == "helper"]
        if action == "transfer":
            # Передать ремонт: исполнитель теперь только он.
            masters, helpers = [target], [h for h in helpers if h != target]
        elif action == "master":
            helpers = [h for h in helpers if h != target]
            if target not in masters:
                masters.append(target)
        elif action == "helper":
            masters = [m for m in masters if m != target]
            if target not in helpers:
                helpers.append(target)
        else:  # remove
            masters = [m for m in masters if m != target]
            helpers = [h for h in helpers if h != target]

        try:
            if action == "helper" and target in [
                m.user_id for m in repair.masters if (m.kind or "master") != "helper"
            ]:
                # Понижение мастера до помощника — двумя запросами: удаление и
                # вставка той же пары (repair_id, user_id) в одном flush
                # упирается в уникальный индекс repair_masters.
                await repairs_api.update_repair(
                    repair_id, RepairUpdate(master_ids=masters), db, user
                )
                await repairs_api.update_repair(
                    repair_id, RepairUpdate(helper_ids=helpers), db, user
                )
            else:
                await repairs_api.update_repair(
                    repair_id,
                    RepairUpdate(master_ids=masters, helper_ids=helpers),
                    db,
                    user,
                )
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(nxt, status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/condition")
async def repair_condition(request: Request, repair_id: uuid.UUID):
    """Чип «Состояние»: отметки из списка + свой текст."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        repair = await repairs_api._get_repair_or_404(db, repair_id)
        if not can_access_repair(user, repair):
            return HTMLResponse("Нет доступа", status_code=403)
        if not (can_edit_device_info(user) or user.has_role("admin", "manager", "operator")):
            return HTMLResponse("Недостаточно прав", status_code=403)
        value = _join_marks(form)
        try:
            await repairs_api.update_repair(
                repair_id, RepairUpdate(condition_notes=value), db, user
            )
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(nxt, status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/complectation")
async def repair_complectation(request: Request, repair_id: uuid.UUID):
    """Чип «Комплектация»: что приехало вместе с техникой."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        repair = await repairs_api._get_repair_or_404(db, repair_id)
        if not can_access_repair(user, repair):
            return HTMLResponse("Нет доступа", status_code=403)
        if not (can_edit_device_info(user) or user.has_role("admin", "manager", "operator")):
            return HTMLResponse("Недостаточно прав", status_code=403)
        items = _checked_marks(form)
        # Храним так же, как приёмка: словарь {название: True}.
        complectation = {name: True for name in items}
        try:
            await repairs_api.update_repair(
                repair_id, RepairUpdate(complectation=complectation), db, user
            )
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(nxt, status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/delivery")
async def repair_delivery(request: Request, repair_id: uuid.UUID):
    """Чип «Доставка»: была ли доставка и телефон доставщика."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        repair = await repairs_api._get_repair_or_404(db, repair_id)
        if not can_access_repair(user, repair):
            return HTMLResponse("Нет доступа", status_code=403)
        if not user.has_role("admin", "manager", "operator"):
            return HTMLResponse("Недостаточно прав", status_code=403)
        is_delivery = (form.get("is_delivery") or "").strip() in ("1", "true", "on", "yes", "да")
        payload = RepairUpdate(
            is_delivery=is_delivery,
            delivery_courier_phone=(form.get("courier_phone") or "").strip() or None,
            delivery_district=(form.get("delivery_district") or "").strip() or None,
            delivery_comment=(form.get("delivery_comment") or "").strip() or None,
        )
        try:
            await repairs_api.update_repair(repair_id, payload, db, user)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(nxt, status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/issue")
async def repair_issue(request: Request, repair_id: uuid.UUID):
    """Отметить, что клиент забрал технику (заполняет `issued_at`)."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        if not can_finish_repair(user):
            return HTMLResponse("Только админ или оператор", status_code=403)
        try:
            await repairs_api.issue_repair(repair_id, db, user)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(nxt, status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/admin")
async def repair_admin_edit(request: Request, repair_id: uuid.UUID):
    """Админ правит все поля карточки: клиент, техника, жалоба, доставка, ETA."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        if not can_delete_repair(user):
            return HTMLResponse("Только администратор", status_code=403)
        form = await request.form()

        def _blank(key):
            v = (form.get(key) or "").strip()
            return v or None

        eta_raw = (form.get("eta_days") or "").strip()
        try:
            eta_days = int(eta_raw) if eta_raw else None
        except ValueError:
            eta_days = None

        complectation = None
        if "complectation" in form:
            comp_raw = (form.get("complectation") or "").strip()
            complectation = {
                item.strip(): True for item in comp_raw.split(",") if item.strip()
            } or None

        payload = RepairUpdate(
            device_type=normalize_class(_blank("device_type")) if _blank("device_type") else None,
            brand=_blank("brand"),
            model=_blank("model"),
            serial=_blank("serial"),
            fault_client=_blank("fault_client"),
            fault_master=_blank("fault_master"),
            condition_notes=_blank("condition_notes"),
            contact2_name=_blank("contact2_name"),
            contact2_phone=_blank("contact2_phone"),
            contact2_relation=_blank("contact2_relation"),
            is_delivery=(form.get("is_delivery") or "").strip()
            in ("1", "true", "on", "yes"),
            delivery_district=_blank("delivery_district"),
            delivery_comment=_blank("delivery_comment"),
            eta_days=eta_days,
            complectation=complectation,
        )
        try:
            await repairs_api.update_repair(repair_id, payload, db, user)
            client_name = _blank("client_name")
            client_phone = _blank("client_phone")
            if client_name or client_phone:
                repair = await repairs_api._get_repair_or_404(db, repair_id)
                await repairs_api.update_client(
                    repair.client_id,
                    repairs_api.ClientUpdate(full_name=client_name, phone=client_phone),
                    db,
                    user,
                )
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(f"/repairs/{repair_id}", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/delete")
async def repair_admin_delete(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        try:
            await repairs_api.delete_repair(repair_id, db, user)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse("/repairs", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/device")
async def repair_device_edit(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        payload = RepairUpdate(
            brand=(form.get("brand") or "").strip() or None,
            model=(form.get("model") or "").strip() or None,
            serial=(form.get("serial") or "").strip() or None,
        )
        await repairs_api.update_repair(repair_id, payload, db, user)
        return RedirectResponse(f"/repairs/{repair_id}", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/parts/add")
async def repair_add_part(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        part_id = form.get("part_id") or None
        name = (form.get("name") or "").strip() or None
        price = (form.get("price") or "").strip().replace(",", ".")
        try:
            qty = int(form.get("qty") or 1)
            qty = max(qty, 1)
        except (TypeError, ValueError):
            qty = 1
        try:
            price_val = float(price) if price else None
        except ValueError:
            return HTMLResponse("Некорректная цена запчасти.", status_code=400)
        add = RepairPartAdd(
            part_id=uuid.UUID(part_id) if part_id else None,
            name=name,
            qty=qty,
            price=price_val,
        )
        await parts_api.add_repair_part(repair_id, add, db, user)
        return RedirectResponse(f"/repairs/{repair_id}#parts", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/parts/{rp_id}/delete")
async def repair_del_part(request: Request, repair_id: uuid.UUID, rp_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        await parts_api.remove_repair_part(repair_id, rp_id, db, user)
        return RedirectResponse(f"/repairs/{repair_id}#parts", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/payments/add")
async def repair_add_payment(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        raw_amount = (form.get("amount") or "").strip().replace(",", ".")
        try:
            amount = float(raw_amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            return HTMLResponse("Введите корректную сумму платежа (положительное число).", status_code=400)
        method = form.get("method", "cash")
        if method not in ("cash", "card", "transfer"):
            method = "cash"
        payload = PaymentCreate(amount=amount, method=method)
        await payments_api.add_payment(repair_id, payload, db, user)
        return RedirectResponse(f"/repairs/{repair_id}#pay", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/payments/{payment_id}/delete")
async def repair_delete_payment(request: Request, repair_id: uuid.UUID, payment_id: uuid.UUID):
    """Сторно платежа из карточки ремонта (право `refund`)."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        await payments_api.delete_payment(payment_id, db, user)
        return RedirectResponse(f"/repairs/{repair_id}#pay", status_code=303)
    finally:
        await db.close()


def _safe_next(raw: str | None, fallback: str) -> str:
    value = (raw or "").strip() or fallback
    if not value.startswith("/repairs"):
        return fallback
    return value


@router.post("/repairs/{repair_id}/finish")
async def repair_finish(request: Request, repair_id: uuid.UUID):
    """Только статус «Завершён». SMS клиенту — отдельной кнопкой."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException
        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        try:
            await repairs_api.finish_repair(repair_id, db, user)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(nxt, status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/notify-client")
async def repair_notify_client(request: Request, repair_id: uuid.UUID):
    return await _notify_client(request, repair_id)


async def _notify_client(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        from fastapi import HTTPException

        try:
            result = await repairs_api.notify_client_ready(repair_id, db, user)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        sms_ok = "1" if result.get("sms_sent") else "0"
        detail = quote(str(result.get("sms_detail") or ""), safe="")
        sep = "&" if "?" in nxt else "?"
        return RedirectResponse(
            f"{nxt}{sep}just=notified&sms={sms_ok}&sms_detail={detail}",
            status_code=303,
        )
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/print")
async def repair_print(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        await prints_api.create_print_job(
            repair_id=repair_id, db=db, user=user, request=request
        )
        sep = "&" if "?" in nxt else "?"
        return RedirectResponse(f"{nxt}{sep}printed=blank", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/print-label")
async def repair_print_label(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        await prints_api.create_label_print_job(
            repair_id=repair_id, db=db, user=user, request=request
        )
        sep = "&" if "?" in nxt else "?"
        return RedirectResponse(f"{nxt}{sep}printed=label", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/print-client-label")
async def repair_print_client_label(request: Request, repair_id: uuid.UUID):
    """Клиентская этикетка с QR на публичный статус (для выдачи клиенту)."""
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        nxt = _safe_next(form.get("next"), f"/repairs/{repair_id}")
        await prints_api.create_client_label_print_job(
            repair_id=repair_id, db=db, user=user, request=request
        )
        sep = "&" if "?" in nxt else "?"
        return RedirectResponse(f"{nxt}{sep}printed=client-label", status_code=303)
    finally:
        await db.close()


@router.get("/repairs/by-number/{number}")
async def repair_by_number(request: Request, number: str):
    """Редирект на карточку по номеру (ссылки из чата)."""
    db, _user, redir = await _require(request)
    if redir:
        return redir
    try:
        row = await db.execute(select(Repair).where(Repair.number == number))
        repair = row.scalar_one_or_none()
        if repair is None:
            return HTMLResponse("Ремонт не найден", status_code=404)
        return RedirectResponse(f"/repairs/{repair.id}", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/photos")
async def repair_upload_photo(request: Request, repair_id: uuid.UUID):
    """Загрузка фото техники (multipart). Переиспользует API-обработчик."""

    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            caption = form.get("caption")
            await repairs_api.upload_photo(
                repair_id=repair_id, db=db, user=user,
                file=upload, caption=caption,
            )
        return RedirectResponse(f"/repairs/{repair_id}#log", status_code=303)
    finally:
        await db.close()
