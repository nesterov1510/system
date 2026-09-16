"""Приёмка без аккаунта — страница /intake.

Технику может оформить человек без входа в систему (планшет на стойке, точка
приёма, филиал). Страница устроена ровно как обычная приёмка сотрудника:
сначала выбор типа техники, затем та же карточка с полями клиента, техники,
комплектации, состояния, неисправности, доставки и фото. Отличие одно —
нельзя выбрать мастера.

Ремонт создаётся в статусе «Новый» и уходит в общий список «Все ремонты»:
дальше его берёт свободный мастер («Взять в работу») либо мастера назначает
администратор.

Принявшим сотрудником указывается служебная учётка «Приёмка без аккаунта»
(intake@msb.local, active=False — войти под ней нельзя), поэтому в списке и
журнале видно, откуда запись.

Доступность и необязательный код доступа настраиваются в
«Админ → Настройки → Приёмка без аккаунта» (настройка `public_intake`).
"""
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db.models import City, RepairPhoto
from app.db.seed import get_public_intake_user
from app.db.session import async_session_factory
from app.routers import prints as prints_api
from app.routers import repairs as repairs_api
from app.services.settings import get_public_intake
from app.webui.catalog import DEVICE_CLASSES, normalize_class
from app.webui.deps import get_web_user
from app.webui.helpers import base_context
from app.webui.intake_form import parse_intake_form, validate_phones
from app.webui.templating import render_async

router = APIRouter(tags=["webui-intake-public"])

# Та же карточка приёмки, что и у сотрудника, но в самостоятельной оболочке
# (без бокового меню и шапки) и без выбора мастера.
PUBLIC_LAYOUT = "public/_plain.html"


def _db():
    return async_session_factory()


async def _cities(db) -> list[City]:
    from sqlalchemy import select

    rows = await db.execute(select(City).order_by(City.name))
    return list(rows.scalars().all())


async def _complectation(db):
    from sqlalchemy import select

    from app.db.models import ComplectationItem

    rows = (
        await db.execute(select(ComplectationItem).order_by(ComplectationItem.sort))
    ).scalars().all()
    return list(rows)


def _code_ok(provided: str, expected: str) -> bool:
    # compare_digest для str требует ASCII: код может быть и кириллическим,
    # поэтому сравниваем байты (иначе страница падала бы с TypeError).
    return secrets.compare_digest(
        (provided or "").strip().encode("utf-8"), (expected or "").encode("utf-8")
    )


async def _code_page(request: Request, error: str | None = None) -> HTMLResponse:
    """Страница ввода кода доступа (показывается, только если код задан)."""
    html = await render_async(
        "public/intake_code.html", request=request, user=None, error=error
    )
    return HTMLResponse(html, status_code=403 if error else 200)


async def _intake_context(request, db, *, form: dict, error: str | None, sel_type, key: str):
    """Контекст карточки приёмки — тот же набор полей, что у сотрудников."""
    form = dict(form or {})
    form.setdefault("key", key)
    ctx = await base_context(
        request, await get_web_user(request), active="/intake",
        cities=await _cities(db),
        masters=[],                      # мастера на публичной приёмке не выбирают
        complectation=await _complectation(db),
        device_classes=DEVICE_CLASSES,
        brands=[], error=error, form=form, sel_type=sel_type,
        can_assign=False, can_self_assign=False,
        public_mode=True, public_layout=PUBLIC_LAYOUT,
    )
    return ctx


@router.get("/intake", response_class=HTMLResponse)
async def public_intake_form(request: Request, key: str = "", type: str | None = None):
    db = _db()
    try:
        cfg = await get_public_intake(db)
        if not cfg["enabled"]:
            return HTMLResponse("Not Found", status_code=404)
        if cfg["code"] and not _code_ok(key, cfg["code"]):
            return await _code_page(request)

        # Без ?type= показываем выбор типа техники — как в обычной приёмке.
        sel = normalize_class(type) if type else None
        ctx = await _intake_context(
            request, db, form={}, error=None, sel_type=sel, key=key
        )
        html = await render_async("repairs/new.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/intake", response_class=HTMLResponse)
async def public_intake_submit(request: Request):
    db = _db()
    try:
        cfg = await get_public_intake(db)
        if not cfg["enabled"]:
            return HTMLResponse("Not Found", status_code=404)
        form = await request.form()
        key = (form.get("key") or "").strip()
        if cfg["code"] and not _code_ok(key, cfg["code"]):
            return await _code_page(request, error="Неверный код доступа")

        sel = normalize_class(form.get("device_type")) if form.get("device_type") else None
        submitted = {k: v for k, v in form.items()}
        submitted["equipment"] = form.getlist("equipment")
        submitted["condition"] = form.getlist("condition")

        async def _form_page(message: str, status: int = 400) -> HTMLResponse:
            ctx = await _intake_context(
                request, db, form=submitted, error=message, sel_type=sel, key=key
            )
            return HTMLResponse(
                await render_async("repairs/new.html", **ctx), status_code=status
            )

        # Телефон проверяем до создания: правила те же, что и на приёмке
        # сотрудника (+993, код оператора, 6 цифр).
        phone_err = validate_phones(form)
        if phone_err:
            return await _form_page(phone_err)
        if not (form.get("full_name") or "").strip():
            return await _form_page("Укажите имя и фамилию заказчика")
        if not (form.get("city_id") or "").strip():
            return await _form_page("Выберите город")

        try:
            # Мастера на публичной приёмке не назначают: ремонт уходит в очередь
            # «Новые», где его берёт мастер или назначает администратор.
            payload = parse_intake_form(form, master_id=None)
            user = await get_public_intake_user(db)
            out = await repairs_api.create_repair(
                payload=payload, db=db, user=user, idempotency_key=None
            )
        except Exception as exc:  # HTTPException(400/403) из API приёмки
            return await _form_page(str(getattr(exc, "detail", None) or "Не удалось оформить приёмку"))
        rid = out.id

        # --- Фото состояния при приёмке (как в обычной приёмке) ---
        try:
            from app.services.storage import object_key_for, save_object

            uploads = [f for f in form.getlist("photos") if getattr(f, "filename", "")]
            cam = form.get("photo_camera")
            if getattr(cam, "filename", ""):
                uploads.append(cam)
            for f in uploads[:12]:
                data = await f.read()
                if not data:
                    continue
                obj_key = object_key_for(str(rid), f.filename or "photo.jpg")
                await save_object(data, obj_key)
                db.add(RepairPhoto(
                    repair_id=rid, object_key=obj_key,
                    caption="Состояние при приёмке", uploaded_by=user.id,
                ))
            if uploads:
                await db.commit()
        except Exception:
            pass  # фото не должны ломать приёмку

        # --- Автопечать при приёмке (та же настройка, что у сотрудников) ---
        label_printed = False
        try:
            from app.core.permissions import can_print
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

        ctx = await _intake_context(request, db, form={}, error=None, sel_type=None, key=key)
        ctx.update(
            number=out.number,
            public_url=f"/r/{out.public_token}",
            device=out.device_type,
            printed=label_printed,
        )
        html = await render_async("public/intake_done.html", **ctx)
        return HTMLResponse(html, status_code=201)
    finally:
        await db.close()
