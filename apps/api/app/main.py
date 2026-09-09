import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.base import Base
from app.db.datamigrate import run_data_migrations
from app.db.migrate import run_migrations
from app.db.models import *  # noqa: F401,F403 — register all models
from app.db.seed import seed
from app.db.session import async_session_factory, engine
from app.on_off_debug import (
    debug_http_log,
    debug_info_print,
    debug_success_print,
    flush_log_writes,
)
from app.routers import (
    admin,
    ai,
    auth,
    callcenter,
    chat,
    equipment,
    lookups,
    notifications,
    parts,
    payments,
    prices,
    prints,
    public,
    repairs,
    stats,
    ws,
)
from app.services.reminders import reminder_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP: create tables + seed. Replace with Alembic migrations later.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Новые колонки в уже существующих таблицах (create_all их не добавляет).
    await run_migrations(engine)
    async with async_session_factory() as db:
        await seed(db)
        # Одноразовые пересчёты уже лежащих в БД значений (идемпотентно).
        await run_data_migrations(db)
    # Local file storage for photos (MVP).
    if settings.STORAGE_MODE == "local":
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    # Стартовые события в журнал debug-мониторинга (/admin/logs).
    debug_success_print(
        f"MSB API запущен: host={settings.API_PREFIX}, storage={settings.STORAGE_MODE}",
        source="app.start",
    )
    debug_info_print(
        f"Напоминания о выдаче: {'вкл' if settings.REMINDER_ENABLED else 'выкл'}",
        source="app.start",
    )

    # Фоновая задача: ежедневные SMS-напоминания «заберите технику».
    # Живёт в том же процессе, что и API (при `--workers 1` — одна копия;
    # на нескольких воркерах от двойной отправки защищает условный UPDATE
    # в services/reminders.py).
    reminder_stop = asyncio.Event()
    reminder_task = None
    if settings.REMINDER_ENABLED:
        reminder_task = asyncio.create_task(reminder_loop(reminder_stop))
    try:
        yield
    finally:
        reminder_stop.set()
        if reminder_task is not None:
            reminder_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reminder_task
        # Дописать остаток журнала попыток IP-контроля перед остановкой.
        with contextlib.suppress(Exception):
            from app.services import ip_access
            await ip_access.flush_log()
        # Дописать очередь debug-логов (фоновый поток записи).
        with contextlib.suppress(Exception):
            flush_log_writes()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# IP-контроль доступа (настраивается администратором в /admin/settings).
# Белый/чёрный список IP клиентов; правила читаются из БД с коротким кэшем.
# Loopback всегда разрешён, чтобы админ не заблокировал сам себя.
# --------------------------------------------------------------------------
from starlette.responses import PlainTextResponse

from app.services import ip_access


@app.middleware("http")
async def ip_access_control(request, call_next):
    rules = await ip_access.get_rules_cached(async_session_factory)
    if rules.get("mode") in ("whitelist", "blacklist"):
        peer = request.client.host if request.client else None
        ip = ip_access.extract_client_ip(
            request.headers, peer, trust_proxy=bool(rules.get("trust_proxy"))
        )
        allowed = ip_access.client_ip_allowed(
            ip, rules["mode"], rules.get("whitelist", []), rules.get("blacklist", [])
        )
        # Пишем в журнал попыток подключения (кроме loopback — это сам сервер
        # или админ через localhost; такие запросы неинтересны и только шумят).
        if not ip_access.is_loopback(ip):
            ip_access.record_attempt(
                ip,
                allowed=allowed,
                mode=rules["mode"],
                path=request.url.path,
                user_agent=request.headers.get("user-agent"),
            )
        if not allowed:
            return PlainTextResponse(
                "Доступ с вашего IP-адреса запрещён настройками IP-контроля.\n"
                f"Ваш IP: {ip or 'не определён'}\n"
                "Обратитесь к администратору системы.",
                status_code=403,
            )
    return await call_next(request)


# --------------------------------------------------------------------------
# Лёгкий request-лог для debug-мониторинга (/admin/logs).
# Каждый HTTP-запрос пишется на уровень INFO (или ERROR при 5xx), кроме
# статики, служебных маршрутов и самого poll-эндпоинта мониторинга — они
# только шумят (тот же смысл, что werkzeug-фильтр в архиве on_off_debug).
# --------------------------------------------------------------------------
_DEBUG_SKIP_PREFIXES = ("/static", "/docs", "/openapi.json", "/health")
_DEBUG_SKIP_EXACT = {"/admin/logs/panel", "/admin/logs/stream"}


@app.middleware("http")
async def debug_request_log(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if (
        not path.startswith(_DEBUG_SKIP_PREFIXES)
        and path not in _DEBUG_SKIP_EXACT
        and not path.startswith("/admin/logs/")
    ):
        debug_http_log(
            is_error=response.status_code >= 500,
            message=f"{request.method} {path} -> {response.status_code}",
        )
    return response


api_prefix = settings.API_PREFIX

app.include_router(auth.router, prefix=api_prefix)
app.include_router(chat.router, prefix=api_prefix)
app.include_router(lookups.router, prefix=api_prefix)
app.include_router(repairs.router, prefix=api_prefix)
app.include_router(callcenter.router, prefix=api_prefix)
app.include_router(prices.router, prefix=api_prefix)
app.include_router(parts.router, prefix=api_prefix)
app.include_router(equipment.router, prefix=api_prefix)
app.include_router(payments.router, prefix=api_prefix)
app.include_router(stats.router, prefix=api_prefix)
app.include_router(ai.router, prefix=api_prefix)
app.include_router(notifications.router, prefix=api_prefix)
app.include_router(public.router, prefix=api_prefix)
app.include_router(prints.router, prefix=api_prefix)
app.include_router(admin.router, prefix=api_prefix)
app.include_router(ws.router)  # WS has no prefix

# --------------------------------------------------------------------------
# Python server-rendered web UI (Jinja2 + HTMX) — интерфейс из архива.
# Страницы на тех же моделях/сервисах/правах, что и JSON-API.
# --------------------------------------------------------------------------
from pathlib import Path as _Path

from app.webui import (
    routes_admin as _web_admin,
)
from app.webui import (
    routes_auth as _web_auth,
)
from app.webui import (
    routes_chat as _web_chat,
)
from app.webui import (
    routes_misc as _web_misc,
)
from app.webui import (
    routes_public as _web_public,
)
from app.webui import (
    routes_repairs as _web_repairs,
)

_web_static_dir = str(_Path(__file__).parent / "webui" / "static")
app.mount("/static", StaticFiles(directory=_web_static_dir), name="webui-static")

# Публичная страница клиента (без авторизации) — регистрируется до общих.
app.include_router(_web_public.router)
app.include_router(_web_auth.router)
app.include_router(_web_repairs.router)
app.include_router(_web_misc.router)
app.include_router(_web_chat.router)
app.include_router(_web_admin.router)


@app.get("/", include_in_schema=False)
async def _root():
    return RedirectResponse("/repairs", status_code=303)


# Serve uploaded photos (local storage mode).
if settings.STORAGE_MODE == "local":
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    app.mount("/media", StaticFiles(directory=settings.UPLOAD_DIR), name="media")


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
