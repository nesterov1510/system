"""Публичная страница статуса ремонта по QR-токену (/r/{token}).

Анонимная: отдаёт только публичные поля (без диагноза мастера, себестоимости
и телефона клиента). Rate-limit переиспользуется из API-слоя.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db.session import async_session_factory
from app.routers import public as public_api
from app.webui.templating import render_async

router = APIRouter(tags=["webui-public"])

# Порядок этапов для полоски прогресса на публичной странице.
PROGRESS = ["Принято", "Диагностика", "Согласование", "Ожидание запчастей",
            "В ремонте", "Готово к выдаче", "Выдано"]


@router.get("/r/{token}", response_class=HTMLResponse)
async def public_page(request: Request, token: str):
    db = async_session_factory()
    try:
        try:
            data = await public_api.public_repair(token, db, request)
        except Exception as e:
            status_code = getattr(e, "status_code", 404)
            html = await render_async("public/notfound.html",
                request=request, user=None
            )
            return HTMLResponse(html, status_code=status_code)

        # Индекс прогресса (терминальные статусы).
        idx = PROGRESS.index(data.status) if data.status in PROGRESS else \
              (6 if data.status in ("Выдано",) else 2)
        ctx = {
            "request": request, "user": None, "d": data,
            "progress": PROGRESS, "progress_idx": idx,
        }
        html = await render_async("public/status.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()
