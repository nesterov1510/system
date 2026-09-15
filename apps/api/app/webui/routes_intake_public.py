"""Приёмка без аккаунта — страница /intake.

Технику может оформить человек без входа в систему (планшет на стойке, точка
приёма, филиал). Ремонт создаётся в статусе «Новый» и уходит в общий список
«Все ремонты»: дальше его берёт свободный мастер (кнопка «Взять в работу») либо
мастера назначает администратор.

Принявшим сотрудником указывается служебная учётка «Приёмка без аккаунта»
(intake@msb.local, active=False — войти под ней нельзя), поэтому в списке и
журнале видно, откуда запись.

Доступность и необязательный код доступа настраиваются в
«Админ → Настройки → Приёмка без аккаунта» (настройка `public_intake`).
"""
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db.models import City
from app.db.seed import get_public_intake_user
from app.db.session import async_session_factory
from app.routers import repairs as repairs_api
from app.services.settings import get_consent_repair_text, get_legal_text, get_public_intake
from app.webui.catalog import DEVICE_CLASSES, normalize_class
from app.webui.intake_form import parse_intake_form, validate_phones
from app.webui.templating import render_async

router = APIRouter(tags=["webui-intake-public"])


def _db():
    return async_session_factory()


async def _cities(db) -> list[City]:
    from sqlalchemy import select

    rows = await db.execute(select(City).order_by(City.name))
    return list(rows.scalars().all())


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


async def _form_context(request, db, *, form: dict, error: str | None, sel_type):
    cities = await _cities(db)
    return {
        "request": request,
        "user": None,
        "cities": cities,
        "device_classes": DEVICE_CLASSES,
        "form": form,
        "error": error,
        "sel_type": sel_type,
        "legal_text": await get_legal_text(db),
        "consent_repair_text": await get_consent_repair_text(db),
    }


@router.get("/intake", response_class=HTMLResponse)
async def public_intake_form(request: Request, key: str = "", type: str | None = None):
    db = _db()
    try:
        cfg = await get_public_intake(db)
        if not cfg["enabled"]:
            return HTMLResponse("Not Found", status_code=404)
        if cfg["code"] and not _code_ok(key, cfg["code"]):
            return await _code_page(request)

        sel = normalize_class(type) if type else None
        ctx = await _form_context(
            request, db, form={"key": key}, error=None, sel_type=sel
        )
        html = await render_async("public/intake.html", **ctx)
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
        submitted = {k: v for k, v in form.items()}
        submitted["equipment"] = form.getlist("equipment")
        submitted["condition"] = form.getlist("condition")
        key = (form.get("key") or "").strip()
        if cfg["code"] and not _code_ok(key, cfg["code"]):
            return await _code_page(request, error="Неверный код доступа")

        sel = normalize_class(form.get("device_type")) if form.get("device_type") else None

        # Телефон проверяем до создания: правила те же, что и на приёмке
        # сотрудника (+993, код оператора, 6 цифр).
        phone_err = validate_phones(form)
        if phone_err:
            ctx = await _form_context(request, db, form=submitted, error=phone_err, sel_type=sel)
            return HTMLResponse(await render_async("public/intake.html", **ctx), status_code=400)
        if not (form.get("full_name") or "").strip():
            ctx = await _form_context(
                request, db, form=submitted,
                error="Укажите имя и фамилию заказчика", sel_type=sel,
            )
            return HTMLResponse(await render_async("public/intake.html", **ctx), status_code=400)
        if not (form.get("city_id") or "").strip():
            ctx = await _form_context(
                request, db, form=submitted, error="Выберите город", sel_type=sel
            )
            return HTMLResponse(await render_async("public/intake.html", **ctx), status_code=400)

        try:
            # Мастера на публичной приёмке не назначают: ремонт уходит в очередь
            # «Новые», где его берёт мастер или назначает администратор.
            payload = parse_intake_form(form, master_id=None)
            user = await get_public_intake_user(db)
            out = await repairs_api.create_repair(
                payload=payload, db=db, user=user, idempotency_key=None
            )
        except Exception as exc:  # HTTPException(400/403) из API приёмки
            message = getattr(exc, "detail", None) or "Не удалось оформить приёмку"
            ctx = await _form_context(
                request, db, form=submitted, error=str(message), sel_type=sel
            )
            return HTMLResponse(await render_async("public/intake.html", **ctx), status_code=400)

        ctx = await _form_context(request, db, form={}, error=None, sel_type=None)
        ctx.update(
            number=out.number,
            public_url=f"/r/{out.public_token}",
            device=out.device_type,
        )
        html = await render_async("public/intake_done.html", **ctx)
        return HTMLResponse(html, status_code=201)
    finally:
        await db.close()
