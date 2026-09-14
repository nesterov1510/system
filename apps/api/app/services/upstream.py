"""Клиентская страница без доступа к базе данных.

Публичный сервер (PUBLIC_ONLY=true) не держит PostgreSQL и не знает его адреса:
статус ремонта он берёт у внутреннего сервера по HTTP — `GET /api/public/r/{token}`.
Так клиентская часть выносится на вторую машину, а база остаётся только внутри.

Внутренний сервер задаётся переменной `PUBLIC_UPSTREAM_URL`,
например `http://192.168.8.81:8085`.
"""
import httpx

from app.core.config import settings
from app.schemas.repair import PublicRepairOut

# Секунд на запрос к внутреннему серверу. Страницу клиента открывают с телефона,
# ждать дольше бессмысленно — лучше показать «сервис недоступен».
UPSTREAM_TIMEOUT = 10.0


class UpstreamUnavailable(Exception):
    """Внутренний сервер не ответил или ответил не 200/404."""


def upstream_base() -> str:
    """Адрес внутреннего сервера без хвоста; пусто — режим не включён."""
    return (settings.PUBLIC_UPSTREAM_URL or "").strip().rstrip("/")


async def fetch_public_repair(token: str) -> PublicRepairOut | None:
    """Публичные данные ремонта с внутреннего сервера.

    Возвращает `None`, если ремонт не найден, и бросает `UpstreamUnavailable`,
    если внутренний сервер недоступен.
    """
    base = upstream_base()
    if not base:
        raise UpstreamUnavailable("PUBLIC_UPSTREAM_URL не задан")
    url = f"{base}/api/public/r/{token}"
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(str(exc)) from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise UpstreamUnavailable(f"внутренний сервер ответил {response.status_code}")
    try:
        return PublicRepairOut.model_validate(response.json())
    except Exception as exc:  # повреждённый/несовместимый ответ
        raise UpstreamUnavailable(f"не удалось разобрать ответ: {exc}") from exc
