"""Админ-страницы: сотрудники и настройки системы (принтер, этикетки, SMS,
общие параметры). Используют те же модели и сервисы, что и JSON-API."""
import asyncio
import base64
import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select

from app.core import permissions as perms
from app.core.security import hash_password
from app.db.models import PrintJob, User, UserRole
from app.db.session import async_session_factory
from app.services import audit
from app.services import settings as settings_svc
from app.webui.deps import bound_user, get_web_user
from app.webui.helpers import base_context
from app.webui.templating import render_async

router = APIRouter(tags=["webui-admin"])

ROLE_CHOICES = ["admin", "manager", "operator", "master", "callcenter"]


def _db():
    return async_session_factory()


async def _require_admin(request):
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return None, None, RedirectResponse("/login", status_code=303)
    if not webuser.user.has_role(UserRole.ADMIN.value):
        return None, None, HTMLResponse("Только администратор", status_code=403)
    db = _db()
    user = await bound_user(db, webuser)
    if user is None:
        await db.close()
        return None, None, RedirectResponse("/login", status_code=303)
    return db, user, None


async def _require_admin_view(request):
    """Проверка прав администратора без открытия сессии БД.

    Для poll-эндпоинтов (мониторинг логов обновляется каждые 2 секунды):
    `get_web_user` уже прочитал пользователя из БД, повторная сессия ни к чему.
    """
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return None, RedirectResponse("/login", status_code=303)
    if not webuser.user.has_role(UserRole.ADMIN.value):
        return None, HTMLResponse("Только администратор", status_code=403)
    return webuser, None


async def _require_logs_view(request):
    """Право на просмотр мониторинга логов (без открытия сессии БД).

    Отдельная функция: её видит не только admin, но и любой пользователь с
    индивидуальным грантом «Мониторинг логов» (см. can_view_logs).
    Используется для фрагмента и SSE-стрима.
    """
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return None, RedirectResponse("/login", status_code=303)
    if not perms.can_view_logs(webuser.user):
        return None, HTMLResponse("Недостаточно прав для просмотра мониторинга", status_code=403)
    return webuser, None


async def _require_logs_page(request):
    """Как _require_logs_view, но с сессией БД (полная страница)."""
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return None, None, RedirectResponse("/login", status_code=303)
    if not perms.can_view_logs(webuser.user):
        return None, None, HTMLResponse("Недостаточно прав для просмотра мониторинга", status_code=403)
    db = _db()
    user = await bound_user(db, webuser)
    if user is None:
        await db.close()
        return None, None, RedirectResponse("/login", status_code=303)
    return db, user, None


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        users = (await db.execute(select(User).order_by(User.name))).scalars().all()

        def _perm_view(u):
            grants = perms.user_grants(u)
            return [
                {
                    "key": f["key"],
                    "label": f["label"],
                    "desc": f["desc"],
                    "by_role": perms.role_grants_feature(u, f["key"]),
                    "granted": f["key"] in grants,
                }
                for f in perms.FEATURES
            ]

        perms_by_user = {u.id: _perm_view(u) for u in users}
        ctx = await base_context(
            request, await get_web_user(request), active="/admin/users",
            users=users, roles=ROLE_CHOICES, perms_by_user=perms_by_user,
        )
        html = await render_async("admin/users.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/admin/users/create")
async def admin_users_create(request: Request):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        f = await request.form()
        email = f.get("email", "").lower().strip()
        exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if exists:
            return HTMLResponse("Пользователь с таким email уже есть", status_code=409)
        u = User(
            name=f.get("name", "").strip(),
            email=email,
            phone=(f.get("phone") or "").strip() or None,
            password_hash=hash_password(f.get("password") or "changeme123"),
            role=f.get("role", "operator"),
            active=True,
        )
        db.add(u)
        await db.commit()
        return RedirectResponse("/admin/users", status_code=303)
    finally:
        await db.close()


@router.post("/admin/users/{user_id}/toggle")
async def admin_users_toggle(request: Request, user_id: uuid.UUID):
    db, user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        if user_id == user.id:
            return HTMLResponse("Нельзя отключить самого себя", status_code=400)
        target = await db.get(User, user_id)
        if target:
            target.active = not target.active
            await db.commit()
        return RedirectResponse("/admin/users", status_code=303)
    finally:
        await db.close()


@router.post("/admin/users/{user_id}/role")
async def admin_users_role(request: Request, user_id: uuid.UUID):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        f = await request.form()
        target = await db.get(User, user_id)
        if target and f.get("role") in ROLE_CHOICES:
            target.role = f.get("role")
            await db.commit()
        return RedirectResponse("/admin/users", status_code=303)
    finally:
        await db.close()


@router.post("/admin/users/{user_id}/permissions")
async def admin_users_permissions(request: Request, user_id: uuid.UUID):
    """Сохранить индивидуальные права доступа пользователя (сверх роли)."""
    db, user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        target = await db.get(User, user_id)
        if target is None:
            return HTMLResponse("Пользователь не найден", status_code=404)
        # У администратора и так все права — менять их бессмысленно и опасно.
        if target.has_role(UserRole.ADMIN.value):
            return RedirectResponse("/admin/users", status_code=303)

        f = await request.form()
        granted = f.getlist("perm")
        target.extra_permissions = [k for k in granted if k in perms.FEATURE_KEYS] or None
        await audit.record(
            db,
            audit.ACTION_USER_UPDATE,
            actor_id=user.id,
            entity="user",
            entity_id=user_id,
            meta={"permissions": target.permissions, "permissions_changed": True},
        )
        await db.commit()
        return RedirectResponse("/admin/users", status_code=303)
    finally:
        await db.close()


@router.post("/admin/users/{user_id}/reset-password")
async def admin_users_reset(request: Request, user_id: uuid.UUID):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        f = await request.form()
        new_pass = f.get("new_password", "").strip()
        if len(new_pass) < 6:
            return HTMLResponse("Пароль должен быть не короче 6 символов", status_code=400)
        target = await db.get(User, user_id)
        if target:
            target.password_hash = hash_password(new_pass)
            await db.commit()
        return RedirectResponse("/admin/users", status_code=303)
    finally:
        await db.close()


# ==========================================================================
# Мониторинг логов (порт on_off_debug из архива 123.zip).
# Журнал пишет модуль app/on_off_debug (log_folder/<уровень>/<дата>/<файл>).
# Просмотр — отдельная функция (can_view_logs), управление — только admin.
# ==========================================================================
def _logs_query_params(request: Request) -> dict:
    def _int(value, default=300):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return {
        "selected_level": request.query_params.get("level", ""),
        "selected_date": request.query_params.get("date", ""),
        "selected_file": request.query_params.get("file", ""),
        "limit": _int(request.query_params.get("limit"), 300),
        "auto_latest": True,
        "q": request.query_params.get("q", ""),
    }


def _logs_view_data(request: Request) -> dict:
    from app.on_off_debug.log_reader import get_log_view_data

    return get_log_view_data(**_logs_query_params(request))


@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs(request: Request):
    db, _user, redir = await _require_logs_page(request)
    if redir:
        return redir
    try:
        webuser = await get_web_user(request)
        data = _logs_view_data(request)
        ctx = await base_context(request, webuser, active="/admin/logs", **data)
        # Управление журналом доступно только администратору.
        if webuser.user.has_role(UserRole.ADMIN.value):
            from app.on_off_debug import get_debug_settings

            ctx["debug_settings"] = get_debug_settings()
        html = await render_async("admin/logs.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.get("/admin/logs/panel", response_class=HTMLResponse)
async def admin_logs_panel(request: Request):
    """HTML-фрагмент (первичная загрузка и fallback-опрос)."""
    _webuser, redir = await _require_logs_view(request)
    if redir:
        return redir
    data = _logs_view_data(request)
    html = await render_async("admin/_logs_panel.html", **data)
    return HTMLResponse(html)


@router.get("/admin/logs/stream")
async def admin_logs_stream(request: Request):
    """SSE-стрим обновлений журнала (вместо HTMX-poll).

    Клиент держит постоянное соединение; сервер отдаёт свежий HTML-фрагмент
    только когда в журнале реально что-то изменилось (по «отпечатку» папки).
    """
    _webuser, redir = await _require_logs_view(request)
    if redir:
        return redir

    from app.on_off_debug import debug_error1_print
    from app.on_off_debug.log_reader import get_log_view_data, get_logs_fingerprint

    params = _logs_query_params(request)

    async def event_stream():
        last_fp = None
        while True:
            if await request.is_disconnected():
                break
            try:
                fp = get_logs_fingerprint()
            except Exception as e:  # noqa: BLE001 — стрим не должен падать
                debug_error1_print(
                    f"logs stream fingerprint: {e}", source="webui.routes_admin.logs_stream"
                )
                await asyncio.sleep(2.0)
                continue
            if fp != last_fp:
                last_fp = fp
                data = get_log_view_data(**params)
                html = await render_async("admin/_logs_panel.html", **data)
                payload = json.dumps(
                    {"html": html, "last_update": data.get("last_update", "")},
                    ensure_ascii=False,
                )
                yield f"event: logs\ndata: {payload}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/admin/logs/settings", response_class=HTMLResponse)
async def admin_logs_settings(request: Request):
    """Форма управления журналом (только admin)."""
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        from app.on_off_debug import get_debug_settings

        ctx = await base_context(
            request,
            await get_web_user(request),
            active="/admin/logs",
            debug_settings=get_debug_settings(),
        )
        html = await render_async("admin/logs_settings.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/admin/logs/settings")
async def admin_logs_settings_save(request: Request):
    """Сохранить параметры журнала (уровни, HTTP-лог, ротация, уведомления)."""
    db, user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        from app.on_off_debug import apply_debug_settings

        f = await request.form()
        updates: dict[str, str] = {}

        bool_keys = [
            "DEBUG_INFO_MODE",
            "DEBUG_SUCCESS_MODE",
            "DEBUG_SUCCESS1_MODE",
            "DEBUG_WARNING_MODE",
            "DEBUG_ERROR_MODE",
            "DEBUG_ERROR1_MODE",
            "DEBUG_CRITICAL_ERROR_MODE",
            "DEBUG_HTTP_LOG_MODE",
            "DEBUG_HTTP_CONSOLE",
            "DEBUG_CRITICAL_NOTIFY_ENABLED",
            "DEBUG_AUTO_CLEAN_ENABLED",
        ]
        for key in bool_keys:
            updates[key] = "True" if f.get(key) in ("1", "on", "true", "True") else "False"

        for key in ("DEBUG_MAX_FILE_KB", "DEBUG_MAX_FILES"):
            try:
                updates[key] = str(max(0, int(f.get(key) or 0)))
            except (TypeError, ValueError):
                updates[key] = "0"

        channel = (f.get("DEBUG_CRITICAL_NOTIFY_CHANNEL") or "none").strip().lower()
        if channel not in ("all", "telegram", "email", "webhook", "none"):
            channel = "none"
        updates["DEBUG_CRITICAL_NOTIFY_CHANNEL"] = channel

        retention = (f.get("DEBUG_LOG_RETENTION") or "").strip()
        if retention:
            updates["DEBUG_LOG_RETENTION"] = retention

        apply_debug_settings(updates)
        await audit.record(
            db,
            audit.ACTION_SETTING_UPDATE,
            actor_id=user.id,
            entity="debug_logs",
            meta={"keys": sorted(updates.keys())},
        )
        await db.commit()
        return RedirectResponse("/admin/logs?saved=1", status_code=303)
    finally:
        await db.close()


@router.post("/admin/logs/clear")
async def admin_logs_clear(request: Request):
    """Полностью очистить журнал (только admin)."""
    db, user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        from app.on_off_debug import clear_all_logs

        removed, freed = clear_all_logs()
        await audit.record(
            db,
            audit.ACTION_SETTING_UPDATE,
            actor_id=user.id,
            entity="debug_logs",
            meta={"action": "clear", "removed_files": removed, "freed_bytes": freed},
        )
        await db.commit()
        return RedirectResponse("/admin/logs?cleared=1", status_code=303)
    finally:
        await db.close()


# ==========================================================================
# Настройки системы (принтер, этикетки, SMS, общие параметры)
# ==========================================================================
def _fnum(v, default=None):
    try:
        s = str(v if v is not None else "").strip().replace(",", ".")
        return float(s) if s else default
    except (TypeError, ValueError):
        return default


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, section: str = "general", saved: str | None = None):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        printer = await settings_svc.get_printer(db)
        label = await settings_svc.get_label_printer(db)
        sms = await settings_svc.get_sms_server(db)
        sms_tpl = await settings_svc.get_sms_templates(db)
        storage = await settings_svc.get_setting(db, "storage_months", {"months": 3})
        brand = await settings_svc.get_setting(db, "brand", {"name": "MSB"})
        currency = await settings_svc.get_currency(db)
        legal_text = await settings_svc.get_legal_text(db)
        consent_text = await settings_svc.get_consent_repair_text(db)
        print_stub = await settings_svc.get_print_stub(db)
        intake_print = await settings_svc.get_intake_auto_print(db)
        ip_control = await settings_svc.get_ip_control(db)
        # Текущий IP админа — чтобы он мог сразу добавить себя в белый список
        # и не заблокировать доступ.
        from app.services import ip_access
        peer = request.client.host if request.client else None
        current_ip = ip_access.extract_client_ip(
            request.headers, peer, trust_proxy=bool(ip_control.get("trust_proxy"))
        )
        recent = (
            (
                await db.execute(
                    select(PrintJob).order_by(PrintJob.created_at.desc()).limit(8)
                )
            )
            .scalars()
            .all()
        )
        # Пароль SMS-шлюза не показываем (как и в JSON-API).
        sms_view = dict(sms)
        sms_view["password"] = "••••••••" if sms.get("password") else ""
        # Журнал попыток подключения (вкладка IP-контроль).
        attempts = await ip_access.get_attempts_summary(db)
        recent_attempts = await ip_access.get_recent_attempts(db, limit=50)
        ctx = await base_context(
            request, await get_web_user(request), active="/admin/settings",
            section=section, saved=saved,
            printer=printer, label=label, sms=sms_view, sms_tpl=sms_tpl,
            storage=storage, brand=brand, currency=currency, recent_jobs=recent,
            settings_svc_legal=legal_text, settings_svc_consent=consent_text,
            ip_control=ip_control, current_ip=current_ip,
            attempts=attempts, recent_attempts=recent_attempts,
            print_stub=print_stub, intake_print=intake_print,
        )
        html = await render_async("admin/settings.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/admin/settings/general")
async def admin_settings_general(request: Request):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        f = await request.form()
        months = int(_fnum(f.get("storage_months"), 3) or 3)
        await settings_svc.set_setting(db, "storage_months", {"months": max(1, months)})
        await settings_svc.set_setting(
            db, "brand", {"name": (f.get("brand_name") or "MSB").strip() or "MSB"}
        )
        await settings_svc.set_setting(
            db,
            "currency",
            {
                "code": (f.get("currency_code") or "TMT").strip() or "TMT",
                "symbol": (f.get("currency_symbol") or "ман.").strip() or "ман.",
                "decimals": int(_fnum(f.get("currency_decimals"), 0) or 0),
            },
        )
        legal = (f.get("legal_text") or "").strip()
        if legal:
            await settings_svc.set_setting(db, "legal_text", {"text": legal})
        consent = (f.get("consent_repair_text") or "").strip()
        if consent:
            await settings_svc.set_setting(db, "consent_repair_text", {"text": consent})
        return RedirectResponse("/admin/settings?section=general&saved=1", status_code=303)
    finally:
        await db.close()


@router.post("/admin/settings/print")
async def admin_settings_print(request: Request):
    """Сохранить тексты и подписи бланка A4 (талон клиента + юридические тексты)."""
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        f = await request.form()

        legal = (f.get("legal_text") or "").strip()
        if legal:
            await settings_svc.set_setting(db, "legal_text", {"text": legal})
        consent = (f.get("consent_repair_text") or "").strip()
        if consent:
            await settings_svc.set_setting(db, "consent_repair_text", {"text": consent})

        stub = {}
        for key in (
            "title", "terms_label", "consent_label", "qr_caption",
            "sign_client", "sign_date", "cut_hint",
        ):
            val = (f.get(f"stub_{key}") or "").strip()
            stub[key] = val
        await settings_svc.set_setting(
            db, "print_stub", stub, "Отрывная часть бланка A4 (талон клиента)"
        )

        # Что печатать автоматически при приёмке (этикетка / бланк / оба / ничего).
        intake_mode = (f.get("intake_auto_print") or "label").strip()
        if intake_mode not in ("label", "blank", "both", "none"):
            intake_mode = "label"
        await settings_svc.set_setting(
            db, "intake_auto_print", {"mode": intake_mode},
            "Автопечать при приёмке: этикетка / бланк / оба / ничего",
        )
        return RedirectResponse("/admin/settings?section=print&saved=1", status_code=303)
    finally:
        await db.close()


@router.post("/admin/settings/printer")
async def admin_settings_printer(request: Request):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        f = await request.form()
        value = {
            "ip": (f.get("printer_ip") or "").strip(),
            "port": int(_fnum(f.get("printer_port"), 631) or 631),
            "mode": (f.get("printer_mode") or "agent").strip(),
            "name": (f.get("printer_name") or "").strip(),
        }
        await settings_svc.set_setting(
            db, "printer", value, "Принтер: IP, порт, режим печати (agent|ipp)"
        )
        return RedirectResponse("/admin/settings?section=printer&saved=1", status_code=303)
    finally:
        await db.close()


@router.post("/admin/settings/label")
async def admin_settings_label(request: Request):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        f = await request.form()
        name = (f.get("label_name") or "").strip()
        ip = (f.get("label_ip") or "").strip()
        if not name or not ip:
            return HTMLResponse("Укажите IP компьютера с CUPS и имя очереди принтера", status_code=400)
        value = {
            "ip": ip,
            "port": int(_fnum(f.get("label_port"), 631) or 631),
            "mode": "cups_remote",
            "name": name,
            "width_mm": 58,
            "height_mm": 38,
            "media": (f.get("label_media") or "Custom.58x38mm").strip(),
        }
        await settings_svc.set_setting(db, "label_printer", value, "CUPS-принтер этикеток 58×38 мм")
        return RedirectResponse("/admin/settings?section=printer&saved=1", status_code=303)
    finally:
        await db.close()


@router.post("/admin/settings/sms")
async def admin_settings_sms(request: Request):
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        f = await request.form()
        current = await settings_svc.get_sms_server(db)
        password = f.get("password") or ""
        # Маскированная/пустая строка — не затираем сохранённый пароль.
        if not password or password.strip("•") == "":
            password = current.get("password", "")
        enabled = f.get("sms_enabled") in ("1", "on", "true", "True")
        value = {
            "enabled": enabled,
            "url": (f.get("sms_url") or "").strip(),
            "username": (f.get("sms_username") or "").strip(),
            "password": password,
            "verify_ssl": f.get("sms_verify_ssl") in ("1", "on", "true", "True"),
            "timeout_sec": _fnum(f.get("sms_timeout"), current.get("timeout_sec", 10.0)) or 10.0,
        }
        if enabled and not value["url"]:
            return HTMLResponse("При включённых SMS укажите адрес шлюза", status_code=400)
        await settings_svc.set_setting(db, "sms_server", value, "SMS-шлюз: адрес, логин/пароль, таймаут")

        await settings_svc.set_setting(
            db,
            "sms_templates",
            {
                "master_assign": (f.get("tpl_master") or "").strip(),
                "ready": (f.get("tpl_ready") or "").strip(),
                "pickup_reminder": (f.get("tpl_reminder") or "").strip(),
            },
            "Шаблоны текстов SMS",
        )
        return RedirectResponse("/admin/settings?section=sms&saved=1", status_code=303)
    finally:
        await db.close()


def _parse_ip_list(raw: str) -> tuple[list[str], list[str]]:
    """Разбить текстовое поле на корректные правила и список ошибок."""
    from app.services import ip_access

    valid: list[str] = []
    errors: list[str] = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        # Разрешаем вводить по одному правилу в строке (textarea).
        for line in token.splitlines():
            line = line.strip()
            if not line:
                continue
            if ip_access.is_valid_rule(line):
                valid.append(line)
            else:
                errors.append(line)
    return ip_access.normalize_rules(valid), errors


@router.post("/admin/settings/ip")
async def admin_settings_ip(request: Request):
    """Сохранить режим IP-контроля и белый/чёрный список IP/сетей."""
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        from app.services import ip_access

        f = await request.form()
        mode = f.get("mode", "off")
        if mode not in ("off", "whitelist", "blacklist"):
            mode = "off"
        trust_proxy = bool(f.get("trust_proxy"))

        white_raw = f.get("whitelist", "") or ""
        black_raw = f.get("blacklist", "") or ""
        white, white_err = _parse_ip_list(white_raw)
        black, black_err = _parse_ip_list(black_raw)

        # Защита от самоблокировки: текущий IP админа обязан быть доступен.
        peer = request.client.host if request.client else None
        current_ip = ip_access.extract_client_ip(request.headers, peer, trust_proxy=trust_proxy)
        block_self = False
        if mode == "blacklist" and ip_access._ip_in_rules(current_ip, black):
            block_self = True
        if mode == "whitelist" and not ip_access.is_loopback(current_ip) and not ip_access._ip_in_rules(current_ip, white):
            block_self = True
        if block_self:
            return HTMLResponse(
                "<h2 style='font-family:sans-serif;padding:24px'>"
                "Сохранение отменено: эти правила заблокировали бы ваш "
                f"текущий IP ({current_ip}). Добавьте его в белый список или "
                "уберите из чёрного.</h2>",
                status_code=400,
            )

        await settings_svc.set_setting(
            db,
            "ip_control",
            {
                "mode": mode,
                "whitelist": white,
                "blacklist": black,
                "trust_proxy": trust_proxy,
            },
            "Контроль доступа по IP (белый/чёрный список)",
        )
        # Сбросить кэш правил, чтобы фильтр применил изменения сразу.
        ip_access.invalidate_cache()

        suffix = "?section=ip&saved=1"
        if white_err or black_err:
            suffix += "&ignored=" + ",".join((white_err + black_err)[:8])
        return RedirectResponse("/admin/settings" + suffix, status_code=303)
    finally:
        await db.close()


@router.post("/admin/settings/ip/log/clear")
async def admin_settings_ip_log_clear(request: Request):
    """Очистить журнал попыток подключения."""
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        from app.services import ip_access

        await ip_access.clear_attempts(db)
        return RedirectResponse("/admin/settings?section=ip&cleared=1", status_code=303)
    finally:
        await db.close()


@router.post("/admin/settings/printer/test")
async def admin_settings_printer_test(request: Request):
    """Тестовая печать бланка А4 (кладёт PDF в очередь print-agent)."""
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        from app.services.print import render_blank_pdf

        printer = await settings_svc.get_printer(db)
        pdf = render_blank_pdf(
            template={"copies": 1, "signature": False},
            number="ТЕСТ-ПЕЧАТЬ", accepted_at="—", city_name="—", branch_name="—",
            client_name="Тестовая печать", client_phone="—", device="Проверка принтера",
            serial="—", complectation="—", fault="—", accepted_by="—", master="—",
            eta_days="", legal_text="", storage_until="—", qr_url="",
        )
        job = PrintJob(
            repair_id=None, template_id="test",
            payload={"pdf_base64": base64.b64encode(pdf).decode("ascii"), "printer": printer},
            status="queued",
        )
        db.add(job)
        await db.commit()
        return RedirectResponse("/admin/settings?section=printer&saved=test", status_code=303)
    finally:
        await db.close()


@router.post("/admin/settings/label/test")
async def admin_settings_label_test(request: Request):
    """Тестовая печать этикетки 58×38 (кладёт PDF в очередь)."""
    db, _user, redir = await _require_admin(request)
    if redir:
        return redir
    try:
        from app.core.config import settings as cfg
        from app.services.print import render_repair_label_pdf

        printer = await settings_svc.get_label_printer(db)
        if not printer.get("name") or not printer.get("ip"):
            return HTMLResponse("Сначала настройте CUPS-принтер этикеток (IP и имя очереди)", status_code=400)
        repair_url = f"{cfg.PUBLIC_BASE_URL.rstrip('/')}/repairs"
        pdf = render_repair_label_pdf(
            repair_number="ТЕСТ-58x38", client_name="Тестовый клиент",
            client_phone="+993 61 000000", repair_url=repair_url,
            complectation="Пульт, Шнур питания", defects="Царапины, Линии на экране",
            width_mm=printer.get("width_mm", 58), height_mm=printer.get("height_mm", 38),
        )
        job = PrintJob(
            repair_id=None, template_id="label-test",
            payload={
                "document_kind": "repair_label",
                "pdf_base64": base64.b64encode(pdf).decode("ascii"),
                "printer": printer, "repair_url": repair_url,
            },
            status="queued",
        )
        db.add(job)
        await db.commit()
        return RedirectResponse("/admin/settings?section=printer&saved=test", status_code=303)
    finally:
        await db.close()
