import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.base import Base
from app.db.datamigrate import run_data_migrations
from app.db.migrate import run_migrations
from app.db.models import *  # noqa: F401,F403 — register all models
from app.db.seed import seed
from app.db.session import async_session_factory, engine
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
    yield


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

# Serve uploaded photos (local storage mode).
if settings.STORAGE_MODE == "local":
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    app.mount("/media", StaticFiles(directory=settings.UPLOAD_DIR), name="media")


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
