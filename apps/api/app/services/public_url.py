"""Публичный адрес сервиса для QR на бланке и этикетке.

Клиент сканирует QR с телефона, поэтому ссылка должна открывать текущий
интерфейс на :8085, а не старый Next.js (:3000/:3030).
"""
from urllib.parse import urlsplit, urlunsplit

from app.core.config import (
    APP_HTTP_PORT,
    LEGACY_FRONTEND_PORTS,
    normalize_public_base_url,
    settings,
)

_LOOPBACK = {"localhost", "127.0.0.1", "::1", "testserver"}


def _origin_from_request(request) -> str | None:
    if request is None:
        return None
    headers = getattr(request, "headers", None) or {}
    host = ""
    proto = ""
    try:
        host = (headers.get("x-forwarded-host") or headers.get("host") or "").split(",")[0].strip()
        proto = (headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    except Exception:
        host = ""
    url = getattr(request, "url", None)
    if not proto:
        proto = getattr(url, "scheme", None) or "http"
    if not host:
        hostname = getattr(url, "hostname", None)
        port = getattr(url, "port", None)
        if not hostname:
            return None
        if port and port not in (80, 443):
            host = f"{hostname}:{port}"
        else:
            host = hostname
    return f"{proto}://{host}"


def public_base_url(request=None) -> str:
    """Origin для QR: запрос печати, иначе PUBLIC_BASE_URL. Порт 3030 → 8085.

    Если оператор открыл панель с localhost, а в env указан LAN-IP — оставляем
    LAN-IP (телефон не откроет localhost), но порт всё равно 8085.
    """
    configured = normalize_public_base_url(settings.PUBLIC_BASE_URL)
    origin = _origin_from_request(request)
    if not origin:
        return configured
    origin = normalize_public_base_url(origin)
    req_host = (urlsplit(origin).hostname or "").lower()
    cfg_host = (urlsplit(configured).hostname or "").lower()
    if req_host in _LOOPBACK and cfg_host not in _LOOPBACK:
        cfg = urlsplit(configured)
        org = urlsplit(origin)
        port = org.port or cfg.port or APP_HTTP_PORT
        if port in LEGACY_FRONTEND_PORTS:
            port = APP_HTTP_PORT
        scheme = org.scheme or cfg.scheme or "http"
        host = cfg.hostname or cfg_host
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            netloc = host
        else:
            netloc = f"{host}:{port}"
        return urlunsplit((scheme, netloc, "", "", ""))
    return origin


def public_status_url(token: str, request=None) -> str:
    return f"{public_base_url(request)}/r/{token}"


def public_repair_url(repair_id, request=None) -> str:
    return f"{public_base_url(request)}/repairs/{repair_id}"
