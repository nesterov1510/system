"""Страницы: клиенты, колл-центр, склад (запчасти/техника), дашборд, профиль."""
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.permissions import (
    can_delete_client,
    can_edit_stock_catalog,
    can_view_analytics,
    has_any_role,
)
from app.db.models import (
    Client,
    Equipment,
    Notification,
    Part,
    PriceItem,
    Repair,
)
from app.db.session import async_session_factory
from app.routers import parts as parts_api
from app.routers import equipment as equipment_api
from app.routers import callcenter as callcenter_api
from app.schemas.parts import PartCreate, PartUpdate
from app.schemas.equipment import EquipmentCreate, EquipmentUpdate
from app.webui.catalog import DEVICE_CLASSES
from app.webui.deps import bound_user, get_web_user
from app.webui.helpers import base_context
from app.webui.templating import render_async
from app.webui.data import is_master_only, master_scope

router = APIRouter(tags=["webui-pages"])


def _db():
    return async_session_factory()


async def _require(request):
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return None, None, RedirectResponse("/login", status_code=303)
    db = _db()
    user = await bound_user(db, webuser)
    if user is None:
        await db.close()
        return None, None, RedirectResponse("/login", status_code=303)
    return db, user, None


# --------------------------------------------------------------------------
# Клиенты
# --------------------------------------------------------------------------
@router.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, q: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        stmt = (
            select(Client, func.count(Repair.id))
            .outerjoin(Repair, Repair.client_id == Client.id)
            .where(Client.deleted_at.is_(None))
            .group_by(Client.id)
            .order_by(func.count(Repair.id).desc(), Client.full_name)
            .limit(300)
        )
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Client.full_name.ilike(like), Client.phone.ilike(like)))
        if is_master_only(user):
            stmt = stmt.where(Repair.id.isnot(None)).where(master_scope(user.id))
        rows = (await db.execute(stmt)).all()
        clients = [{"c": c, "count": cnt} for c, cnt in rows]
        ctx = await base_context(
            request, await get_web_user(request), active="/clients",
            clients=clients, q=q or "",
        )
        html = await render_async("clients.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.get("/clients/{client_id}", response_class=HTMLResponse)
async def client_detail(request: Request, client_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        client = await db.get(Client, client_id)
        if client is None or client.deleted_at is not None:
            return HTMLResponse("Клиент не найден", status_code=404)
        stmt = (
            select(Repair)
            .where(Repair.client_id == client_id)
            .options(selectinload(Repair.master))
            .order_by(Repair.accepted_at.desc())
        )
        if is_master_only(user):
            stmt = stmt.where(master_scope(user.id))
        repairs = (await db.execute(stmt)).scalars().all()
        from app.services.settings import get_currency
        currency = await get_currency(db)
        ctx = await base_context(
            request, await get_web_user(request), active="/clients",
            client=client, repairs=repairs, currency=currency,
            can_edit_client=has_any_role(user, "admin", "manager", "operator"),
            can_delete_client=can_delete_client(user),
        )
        html = await render_async("client_detail.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/clients/{client_id}/update")
async def client_update(request: Request, client_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        from app.routers import repairs as repairs_api

        f = await request.form()
        payload = repairs_api.ClientUpdate(
            full_name=(f.get("full_name") or "").strip() or None,
            phone=(f.get("phone") or "").strip() or None,
        )
        try:
            await repairs_api.update_client(client_id, payload, db, user)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse(f"/clients/{client_id}", status_code=303)
    finally:
        await db.close()


@router.post("/clients/{client_id}/delete")
async def client_delete(request: Request, client_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        from app.routers import repairs as repairs_api

        try:
            await repairs_api.delete_client(client_id, db, user)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse("/clients", status_code=303)
    finally:
        await db.close()


# --------------------------------------------------------------------------
# Колл-центр
# --------------------------------------------------------------------------
@router.get("/callcenter", response_class=HTMLResponse)
async def callcenter_page(request: Request, kind: str = "all"):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        queue = await callcenter_api._queue(db, kind, limit=100)
        ctx = await base_context(
            request, await get_web_user(request), active="/callcenter",
            queue=queue, kind=kind,
        )
        html = await render_async("callcenter.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


# --------------------------------------------------------------------------
# Склад: запчасти + купленная техника
# --------------------------------------------------------------------------
@router.get("/parts", response_class=HTMLResponse)
async def parts_page(request: Request, q: str | None = None, low: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        stmt = select(Part).where(Part.active.is_(True)).order_by(Part.name)
        if q:
            stmt = stmt.where(Part.name.ilike(f"%{q.strip()}%"))
        if low:
            stmt = stmt.where(Part.stock_qty <= Part.min_stock)
        parts = (await db.execute(stmt)).scalars().all()

        eq = (await db.execute(
            select(Equipment).where(Equipment.active.is_(True)).order_by(Equipment.purchased_at.desc())
        )).scalars().all()

        ctx = await base_context(
            request, await get_web_user(request), active="/parts",
            parts=parts, equipment=eq, q=q or "", low=low,
            can_catalog=can_edit_stock_catalog(user),
        )
        html = await render_async("parts.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/parts/create")
async def parts_create(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        f = await request.form()

        def num(k):
            v = (f.get(k) or "").strip().replace(",", ".")
            return float(v) if v else None

        payload = PartCreate(
            name=f.get("name", ""), sku=(f.get("sku") or "") or None,
            category=(f.get("category") or "") or None,
            stock_qty=int(f.get("stock_qty") or 0), min_stock=int(f.get("min_stock") or 0),
            cost_price=num("cost_price"), sell_price=num("sell_price"),
            supplier=(f.get("supplier") or "") or None,
        )
        await parts_api.create_part(payload=payload, db=db, user=user)
        return RedirectResponse("/parts", status_code=303)
    finally:
        await db.close()


@router.post("/parts/{part_id}/update")
async def parts_update(request: Request, part_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        if not can_edit_stock_catalog(user):
            return HTMLResponse("Недостаточно прав для склада", status_code=403)
        f = await request.form()

        def num(k):
            v = (f.get(k) or "").strip().replace(",", ".")
            return float(v) if v else None

        payload = PartUpdate(
            name=(f.get("name") or "").strip() or None,
            sku=(f.get("sku") or "").strip() or None,
            category=(f.get("category") or "").strip() or None,
            stock_qty=int(f.get("stock_qty") or 0) if (f.get("stock_qty") or "").strip() != "" else None,
            min_stock=int(f.get("min_stock") or 0) if (f.get("min_stock") or "").strip() != "" else None,
            cost_price=num("cost_price"),
            sell_price=num("sell_price"),
            supplier=(f.get("supplier") or "").strip() or None,
        )
        try:
            await parts_api.update_part(part_id, payload, db, user, _=True)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse("/parts", status_code=303)
    except Exception as e:
        return HTMLResponse(f"Не удалось сохранить позицию: {getattr(e, 'detail', e)}", status_code=400)
    finally:
        await db.close()


@router.post("/parts/{part_id}/delete")
async def parts_delete(request: Request, part_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        if not can_edit_stock_catalog(user):
            return HTMLResponse("Недостаточно прав для склада", status_code=403)
        try:
            await parts_api.delete_part(part_id, db, user, _=True)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse("/parts", status_code=303)
    finally:
        await db.close()


@router.post("/equipment/create")
async def equipment_create(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        if not can_edit_stock_catalog(user):
            return HTMLResponse("Недостаточно прав для склада", status_code=403)
        f = await request.form()

        def num(k):
            v = (f.get(k) or "").strip().replace(",", ".")
            return float(v) if v else None

        components_raw = (f.get("components") or "").strip()
        components = [c.strip() for c in components_raw.split(",") if c.strip()] or None
        payload = EquipmentCreate(
            name=f.get("name", "").strip(),
            brand=(f.get("brand") or "").strip() or None,
            model=(f.get("model") or "").strip() or None,
            purchase_price=num("purchase_price"),
            storage_place=(f.get("storage_place") or "").strip() or None,
            notes=(f.get("notes") or "").strip() or None,
            components=components,
        )
        await equipment_api.create_equipment(payload=payload, db=db, user=user, _=True)
        return RedirectResponse("/parts", status_code=303)
    except Exception as e:
        return HTMLResponse(f"Не удалось добавить технику: {getattr(e, 'detail', e)}", status_code=400)
    finally:
        await db.close()


@router.post("/equipment/{equipment_id}/update")
async def equipment_update(request: Request, equipment_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        if not can_edit_stock_catalog(user):
            return HTMLResponse("Недостаточно прав для склада", status_code=403)
        f = await request.form()

        def num(k):
            v = (f.get(k) or "").strip().replace(",", ".")
            return float(v) if v else None

        components_raw = (f.get("components") or "").strip()
        components = [c.strip() for c in components_raw.split(",") if c.strip()] or None
        payload = EquipmentUpdate(
            name=(f.get("name") or "").strip() or None,
            brand=(f.get("brand") or "").strip() or None,
            model=(f.get("model") or "").strip() or None,
            purchase_price=num("purchase_price"),
            status=(f.get("status") or "").strip() or None,
            storage_place=(f.get("storage_place") or "").strip() or None,
            notes=(f.get("notes") or "").strip() or None,
            components=components,
        )
        try:
            await equipment_api.update_equipment(equipment_id, payload, db, user, _=True)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse("/parts", status_code=303)
    except Exception as e:
        return HTMLResponse(f"Не удалось сохранить технику: {getattr(e, 'detail', e)}", status_code=400)
    finally:
        await db.close()


@router.post("/equipment/{equipment_id}/delete")
async def equipment_delete(request: Request, equipment_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException

        if not can_edit_stock_catalog(user):
            return HTMLResponse("Недостаточно прав для склада", status_code=403)
        try:
            await equipment_api.delete_equipment(equipment_id, db, user, _=True)
        except HTTPException as e:
            return HTMLResponse(str(e.detail), status_code=e.status_code)
        return RedirectResponse("/parts", status_code=303)
    finally:
        await db.close()


# --------------------------------------------------------------------------
# Дашборд «Курс ремонта»
# --------------------------------------------------------------------------
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        if not can_view_analytics(user):
            return HTMLResponse("Раздел доступен администратору и менеджеру", status_code=403)
        from app.services import stats as stats_service

        overview = await stats_service.overview(db)
        try:
            tiles = await stats_service.tiles(db)
        except Exception:
            tiles = []
        finance_chart = await stats_service.finance_chart(db, period="14d")
        ctx = await base_context(
            request, await get_web_user(request), active="/dashboard",
            overview=overview, tiles=tiles, finance_chart=finance_chart,
        )
        html = await render_async("dashboard.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.get("/dashboard/finance")
async def dashboard_finance(
    request: Request,
    period: str = "14d",
    date_from: str | None = None,
    date_to: str | None = None,
):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        if not can_view_analytics(user):
            return JSONResponse({"ok": False, "error": "Нет доступа"}, status_code=403)
        from app.services import stats as stats_service

        payload = await stats_service.finance_chart(
            db, period=period, date_from=date_from, date_to=date_to,
        )
        return JSONResponse(payload)
    finally:
        await db.close()


# --------------------------------------------------------------------------
# Прайс-лист услуг (справочник цен для приёмки и согласования)
# --------------------------------------------------------------------------
def _can_edit_prices(user) -> bool:
    return "admin" in user.roles or "manager" in user.roles


@router.get("/prices", response_class=HTMLResponse)
async def prices_page(request: Request, q: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        stmt = select(PriceItem).where(PriceItem.active.is_(True)).order_by(
            PriceItem.device_type, PriceItem.brand, PriceItem.fault
        )
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    PriceItem.fault.ilike(like),
                    PriceItem.brand.ilike(like),
                    PriceItem.model_or_line.ilike(like),
                    PriceItem.device_type.ilike(like),
                )
            )
        items = (await db.execute(stmt.limit(300))).scalars().all()
        ctx = await base_context(
            request, await get_web_user(request), active="/prices",
            price_items=items, q=q or "",
            device_classes=DEVICE_CLASSES,
            can_edit_prices=_can_edit_prices(user),
        )
        html = await render_async("prices.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/prices/create")
async def price_create(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        if not _can_edit_prices(user):
            return HTMLResponse("Прайс редактируют администратор или менеджер", status_code=403)

        def num(k):
            v = (f.get(k) or "").strip().replace(",", ".")
            return float(v) if v else None

        f = await request.form()
        device_type = (f.get("device_type") or "").strip() or None
        item = PriceItem(
            device_type=device_type,
            brand=(f.get("brand") or "").strip() or None,
            model_or_line=(f.get("model_or_line") or "").strip() or None,
            fault=(f.get("fault") or "").strip() or None,
            price_min=num("price_min"),
            price_max=num("price_max"),
            price_avg=num("price_avg"),
            typical_days=int(f["typical_days"]) if (f.get("typical_days") or "").strip().isdigit() else None,
            source="manual",
            active=True,
        )
        db.add(item)
        await db.commit()
        return RedirectResponse("/prices", status_code=303)
    finally:
        await db.close()


@router.post("/prices/{price_id}/update")
async def price_update(request: Request, price_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        if not _can_edit_prices(user):
            return HTMLResponse("Недостаточно прав", status_code=403)
        f = await request.form()

        def num(k):
            v = (f.get(k) or "").strip().replace(",", ".")
            return float(v) if v else None

        item = await db.get(PriceItem, price_id)
        if item is None or not item.active:
            return HTMLResponse("Позиция прайса не найдена", status_code=404)
        item.device_type = (f.get("device_type") or "").strip() or None
        item.brand = (f.get("brand") or "").strip() or None
        item.model_or_line = (f.get("model_or_line") or "").strip() or None
        item.fault = (f.get("fault") or "").strip() or None
        item.price_min = num("price_min")
        item.price_max = num("price_max")
        item.price_avg = num("price_avg")
        days = (f.get("typical_days") or "").strip()
        item.typical_days = int(days) if days.isdigit() else None
        await db.commit()
        return RedirectResponse("/prices", status_code=303)
    finally:
        await db.close()


@router.post("/prices/{price_id}/delete")
async def price_delete(request: Request, price_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        if not _can_edit_prices(user):
            return HTMLResponse("Недостаточно прав", status_code=403)
        item = await db.get(PriceItem, price_id)
        if item is not None:
            item.active = False  # мягкое удаление — история согласований сохраняется
            await db.commit()
        return RedirectResponse("/prices", status_code=303)
    finally:
        await db.close()


# --------------------------------------------------------------------------
# Уведомления
# --------------------------------------------------------------------------
@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request, unread: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from app.db.base import utcnow
        stmt = (
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(200)
        )
        if unread:
            stmt = stmt.where(Notification.read_at.is_(None))
        items = (await db.execute(stmt)).scalars().all()
        unread_count = (
            await db.execute(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user.id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
        ctx = await base_context(
            request, await get_web_user(request), active="/notifications",
            notifications=items, unread_count=unread_count, only_unread=bool(unread),
            now=utcnow(),
        )
        html = await render_async("notifications.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/notifications/read-all")
async def notifications_read_all(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from app.db.base import utcnow
        from sqlalchemy import update as sa_update
        await db.execute(
            sa_update(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
            .values(read_at=utcnow())
        )
        await db.commit()
        return RedirectResponse("/notifications", status_code=303)
    finally:
        await db.close()


@router.post("/notifications/{notification_id}/read")
async def notification_read(request: Request, notification_id: uuid.UUID):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        n = await db.get(Notification, notification_id)
        if n is not None and n.user_id == user.id and n.read_at is None:
            from app.db.base import utcnow
            n.read_at = utcnow()
            await db.commit()
        # Если уведомление привязано к ремонту — открываем его, иначе список.
        if n is not None and n.repair_id:
            return RedirectResponse(f"/repairs/{n.repair_id}", status_code=303)
        return RedirectResponse("/notifications", status_code=303)
    finally:
        await db.close()


# --------------------------------------------------------------------------
# Профиль
# --------------------------------------------------------------------------
@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, saved: str | None = None):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        ctx = await base_context(
            request, await get_web_user(request), active="/profile",
            saved=saved, error=None,
        )
        html = await render_async("profile.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/profile-password")
async def profile_password(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from fastapi import HTTPException
        from app.core.security import hash_password, verify_password
        f = await request.form()
        current = f.get("current_password", "")
        new_pass = f.get("new_password", "")
        if not verify_password(current, user.password_hash):
            raise HTTPException(400, "Текущий пароль неверный")
        if len(new_pass) < 6:
            raise HTTPException(400, "Новый пароль должен быть не короче 6 символов")
        user.password_hash = hash_password(new_pass)
        await db.commit()
        return RedirectResponse("/profile?saved=1", status_code=303)
    except Exception as e:
        ctx = await base_context(
            request, await get_web_user(request), active="/profile",
            saved=None, error=str(getattr(e, "detail", e)),
        )
        html = await render_async("profile.html", **ctx)
        return HTMLResponse(html, status_code=400)
    finally:
        await db.close()


@router.post("/profile")
async def profile_save(request: Request):
    db, user, redir = await _require(request)
    if redir:
        return redir
    try:
        from app.routers.auth import update_me
        from app.schemas.auth import ProfileUpdate
        f = await request.form()
        payload = ProfileUpdate(
            name=(f.get("name") or "").strip() or None,
            phone=(f.get("phone") or "").strip() or None,
            telegram=(f.get("telegram") or "").strip() or None,
        )
        await update_me(payload, db, user)
        return RedirectResponse("/profile?saved=1", status_code=303)
    except Exception as e:
        ctx = await base_context(
            request, await get_web_user(request), active="/profile",
            saved=None, error=str(getattr(e, "detail", e)),
        )
        html = await render_async("profile.html", **ctx)
        return HTMLResponse(html, status_code=400)
    finally:
        await db.close()
