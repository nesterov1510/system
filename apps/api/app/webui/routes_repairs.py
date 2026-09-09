"""Серверные страницы: список/доска ремонтов, приёмка, карточка ремонта.

Мутации (создание/обновление ремонта, запчасти, платежи, события, печать)
вызывают те же функции, что и JSON-API, — бизнес-логика не дублируется.
"""
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.permissions import (
    can_access_repair,
    can_add_repair_part,
    can_assign_masters,
    can_edit_device_info,
    can_edit_finances,
    can_finish_repair,
    can_print,
    can_refund_payment,
    can_set_repair_part_price,
    can_take_payment,
    is_master_only,
)
from app.db.models import (
    ComplectationItem,
    Part,
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
from app.webui.catalog import DEVICE_CLASSES, normalize_class
from app.webui.deps import bound_user, get_web_user
from app.webui.helpers import base_context
from app.webui.templating import render_async

router = APIRouter(tags=["webui-repairs"])


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


async def _cities(db):
    from app.db.models import City
    return (await db.execute(select(City).order_by(City.name))).scalars().all()


# --------------------------------------------------------------------------
# Список / доска ремонтов
# --------------------------------------------------------------------------
@router.get("/repairs", response_class=HTMLResponse)
async def repairs_list(request: Request, stage: str | None = None, q: str | None = None,
                       status: str | None = None, view: str = "table", page: int = 1,
                       just: str | None = None, printed: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from app.webui.data import (
            fetch_repairs,
            repair_parts_cost,
            repair_parts_names,
            repair_payments_total,
        )
        repairs, total = await fetch_repairs(
            db, user, stage=stage, status=status, q=q, page=page, page_size=50,
        )
        ids = [r.id for r in repairs]
        parts_cost = await repair_parts_cost(db, ids)
        parts_names = await repair_parts_names(db, ids)
        pays = await repair_payments_total(db, ids)
        currency = await get_currency(db)
        statuses = await get_repair_statuses(db)
        masters = await _masters_list(db)
        # Счётчики этапов для бейджей (агрегат COUNT, без загрузки строк).
        from sqlalchemy import func as _func

        from app.webui.data import STAGE_STATUSES, master_scope
        counts = {"all": 0}

        async def _count(*where):
            stmt = select(_func.count()).select_from(select(Repair.id).where(*where).subquery())
            return (await db.execute(stmt)).scalar() or 0

        for key, sts in STAGE_STATUSES.items():
            where = [Repair.status.in_(sts)]
            if is_master_only(user):
                where.append(master_scope(user.id))
            counts[key] = await _count(*where)
        all_where = [master_scope(user.id)] if is_master_only(user) else []
        counts["all"] = await _count(*all_where)

        stage_labels = [("new", "Новые"), ("diag", "Диагностика"),
                        ("work", "В работе"), ("done", "Завершены")]

        ctx = await base_context(
            request, await get_web_user(request), active="/repairs",
            repairs=repairs, total=total, stage=stage or "all", q=q or "",
            status=status, view=view, page=page, parts_cost=parts_cost,
            parts_names=parts_names, pays=pays, currency=currency,
            statuses=statuses, masters=masters,
            counts=counts, stages=stage_labels,
            just=just, printed=printed,
        )
        html = await render_async(
            "repairs/list.html" if view == "table" else "repairs/board.html"
        , **ctx)
        return HTMLResponse(html)
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
        ctx = await base_context(
            request, await get_web_user(request), active="/repairs/new",
            cities=await _cities(db), masters=await _masters_list(db),
            complectation=await _complectation(db), device_classes=DEVICE_CLASSES,
            brands=[], error=None, form={}, sel_type=sel,
        )
        html = await render_async("repairs/new.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/repairs/new")
async def repair_create(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
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

        is_delivery = bool(form.get("is_delivery"))
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
            brand=(form.get("brand_manual") or form.get("brand") or "").strip() or None,
            model=(form.get("model_manual") or form.get("model") or "").strip() or None,
            serial=(form.get("serial_manual") or form.get("serial") or "").strip() or None,
            complectation=comp or None,
            fault_client=(form.get("fault_client") or "").strip() or None,
            condition_notes=condition_notes,
            master_id=uuid.UUID(form["master_id"]) if form.get("master_id") else None,
            consent_repair=bool(form.get("consent_repair")),
            is_delivery=is_delivery,
            delivery_district=(form.get("delivery_district") or "").strip() or None
            if is_delivery else None,
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
        # По умолчанию печатается этикетка 58×38 (её клеят на технику при
        # клиенте). Что печатать — этикетка / бланк / оба / ничего — выбирается
        # в админке «Настройки → Печать → Автопечать при приёмке».
        label_printed = False
        try:
            from app.services import settings as settings_svc
            repair = await repairs_api._get_repair_or_404(db, rid)
            if can_print(user, repair):
                auto = await settings_svc.get_intake_auto_print(db)
                if auto in ("label", "both"):
                    await prints_api.create_label_print_job(repair_id=rid, db=db, user=user)
                    label_printed = True
                if auto in ("blank", "both"):
                    await prints_api.create_print_job(repair_id=rid, db=db, user=user)
        except Exception:
            pass  # проблемы печати не должны ломать приёмку
        # После сохранения — сразу в список ремонтов с подтверждением.
        return RedirectResponse(
            f"/repairs?just=accepted&printed={'1' if label_printed else '0'}",
            status_code=303,
        )
    except Exception as e:
        _submitted = dict(await request.form())
        ctx = await base_context(
            request, await get_web_user(request), active="/repairs/new",
            cities=await _cities(db), masters=await _masters_list(db),
            complectation=await _complectation(db), device_classes=DEVICE_CLASSES,
            brands=[], error=str(getattr(e, "detail", e)), form=_submitted,
            sel_type=normalize_class(_submitted.get("device_type")) if _submitted.get("device_type") else None,
        )
        html = await render_async("repairs/new.html", **ctx)
        return HTMLResponse(html, status_code=400)
    finally:
        await db.close()


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
async def repair_detail(request: Request, repair_id: uuid.UUID, tab: str = "info",
                        just: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        repair = await _load_repair(db, repair_id)
        if repair is None:
            return HTMLResponse("Ремонт не найден", status_code=404)
        if not can_access_repair(user, repair):
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
        catalog = (await db.execute(
            select(Part).where(Part.active.is_(True), Part.stock_qty > 0).order_by(Part.name)
        )).scalars().all()
        currency = await get_currency(db)
        statuses = await get_repair_statuses(db)
        masters = await _masters_list(db)

        parts_cost = sum(float(p.price or 0) * p.qty for p in parts)
        paid_total = sum(float(p.amount) for p in payments)
        master_ids = [m.user_id for m in repair.masters if (m.kind or "master") != "helper"]

        ctx = await base_context(
            request, await get_web_user(request), active="/repairs",
            repair=repair, parts=parts, payments=payments, photos=photos,
            catalog=catalog, currency=currency, statuses=statuses, masters=masters,
            tab=tab, just=just, parts_cost=parts_cost, paid_total=paid_total,
            master_ids=master_ids,
            can={
                "finance": can_edit_finances(user),
                "assign": can_assign_masters(user),
                "finish": can_finish_repair(user),
                "print": can_print(user, repair),
                "payment": can_take_payment(user),
                "refund": can_refund_payment(user),
                "device": can_edit_device_info(user),
                "addpart": can_add_repair_part(user),
                "setpartprice": can_set_repair_part_price(user),
                "master_only": is_master_only(user),
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
        return RedirectResponse(f"/repairs/{repair_id}?tab=timeline", status_code=303)
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
        return RedirectResponse(f"/repairs/{repair_id}?tab=payment", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/assign")
async def repair_assign(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        form = await request.form()
        ids = [uuid.UUID(x) for x in form.getlist("master_ids") if x]
        payload = RepairUpdate(master_ids=ids or None)
        await repairs_api.update_repair(repair_id, payload, db, user)
        return RedirectResponse(f"/repairs/{repair_id}", status_code=303)
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
        return RedirectResponse(f"/repairs/{repair_id}?tab=parts", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/parts/{rp_id}/delete")
async def repair_del_part(request: Request, repair_id: uuid.UUID, rp_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        await parts_api.remove_repair_part(repair_id, rp_id, db, user)
        return RedirectResponse(f"/repairs/{repair_id}?tab=parts", status_code=303)
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
        return RedirectResponse(f"/repairs/{repair_id}?tab=payment", status_code=303)
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
        return RedirectResponse(f"/repairs/{repair_id}?tab=payment", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/finish")
async def repair_finish(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        await repairs_api.finish_repair(repair_id, db, user)
        return RedirectResponse(f"/repairs/{repair_id}", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/print")
async def repair_print(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        await prints_api.create_print_job(repair_id=repair_id, db=db, user=user)
        return RedirectResponse(f"/repairs/{repair_id}?printed=blank", status_code=303)
    finally:
        await db.close()


@router.post("/repairs/{repair_id}/print-label")
async def repair_print_label(request: Request, repair_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        await prints_api.create_label_print_job(repair_id=repair_id, db=db, user=user)
        return RedirectResponse(f"/repairs/{repair_id}?printed=label", status_code=303)
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
        return RedirectResponse(f"/repairs/{repair_id}?tab=timeline", status_code=303)
    finally:
        await db.close()
