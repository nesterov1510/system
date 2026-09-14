"""Публичная страница статуса ремонта по QR-токену (/r/{token}).

Анонимная: отдаёт только публичные поля (без диагноза мастера, себестоимости
и телефона клиента). Rate-limit переиспользуется из API-слоя.

Два источника данных:
* по умолчанию — локальная БД (внутренний сервер);
* при заданном PUBLIC_UPSTREAM_URL — внутренний сервер по HTTP. Так клиентская
  часть работает на второй машине, у которой нет и не должно быть доступа к БД.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db.models import RepairStatus, map_status
from app.db.session import async_session_factory
from app.routers import public as public_api
from app.services import upstream
from app.webui.templating import render_async

router = APIRouter(tags=["webui-public"])

# Порядок этапов для полоски прогресса на публичной странице.
PROGRESS = list(RepairStatus.ALL)


async def _status_page(request: Request, data) -> HTMLResponse:
    """Отрисовать страницу статуса по публичным данным ремонта."""
    # Индекс прогресса. Устаревшие статусы приводим к актуальным, чтобы
    # старые ремонты не «зависали» на середине полоски.
    status = map_status(data.status) or data.status
    idx = PROGRESS.index(status) if status in PROGRESS else 2
    ctx = {
        "request": request, "user": None, "d": data,
        "progress": PROGRESS, "progress_idx": idx,
    }
    html = await render_async("public/status.html", **ctx)
    return HTMLResponse(html)


async def _not_found(
    request: Request, status_code: int = 404, reason: str | None = None
) -> HTMLResponse:
    html = await render_async(
        "public/notfound.html", request=request, user=None, reason=reason
    )
    return HTMLResponse(html, status_code=status_code)


@router.get("/r/{token}", response_class=HTMLResponse)
async def public_page(request: Request, token: str):
    # Публичный сервер без БД: данные берём у внутреннего сервера по HTTP.
    if upstream.upstream_base():
        try:
            data = await upstream.fetch_public_repair(token)
        except upstream.UpstreamUnavailable:
            # Внутренний сервер недоступен. 502, а не 404: ссылка при этом
            # может быть вполне рабочей, и клиенту нельзя говорить, что ремонт
            # «не найден».
            return await _not_found(request, status_code=502, reason="unavailable")
        if data is None:
            return await _not_found(request, status_code=404)
        return await _status_page(request, data)

    db = async_session_factory()
    try:
        try:
            data = await public_api.public_repair(token, db, request)
        except Exception as e:
            status_code = getattr(e, "status_code", 404)
            return await _not_found(request, status_code=status_code)
        return await _status_page(request, data)
    finally:
        await db.close()
