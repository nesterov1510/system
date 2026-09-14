"""Публичный сервер без базы: статус берётся у внутреннего сервера по HTTP.

Вторая машина, на которую вынесена клиентская часть, не держит PostgreSQL и не
знает его адреса. PUBLIC_UPSTREAM_URL задаёт внутренний сервер; страница
/r/{token} и её JSON проксируются с него.
"""
import httpx
import pytest

from app.schemas.repair import PublicRepairOut
from app.services import upstream

PAYLOAD = {
    "number": "TV-ASG-2026-00001",
    "status": "В работе",
    "device_type": "Телевизоры",
    "brand": "Samsung",
    "model": "UE55",
    "accepted_at": "2026-09-01T10:00:00",
    "eta_days": 3,
    "branch_name": "Центральная точка",
    "branch_phone": "+993 12 000000",
}


def _patch_transport(monkeypatch, handler):
    """Подменить транспорт httpx, оставив настоящую функцию загрузки."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(upstream.httpx, "AsyncClient", factory)


@pytest.fixture()
def with_upstream(monkeypatch):
    from app.core.config import settings

    old = settings.PUBLIC_UPSTREAM_URL
    settings.PUBLIC_UPSTREAM_URL = "http://internal:8085/"
    yield
    settings.PUBLIC_UPSTREAM_URL = old


# --------------------------------------------------------------------------
# Загрузка с внутреннего сервера
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_fetch_returns_public_dto(monkeypatch, with_upstream):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=PAYLOAD)

    _patch_transport(monkeypatch, handler)
    data = await upstream.fetch_public_repair("TOKEN123")
    assert isinstance(data, PublicRepairOut)
    assert data.number == "TV-ASG-2026-00001"
    # хвостой слэш в настройке не должен давать двойной слэш в адресе
    assert seen["url"] == "http://internal:8085/api/public/r/TOKEN123"


@pytest.mark.anyio
async def test_fetch_missing_repair_is_none(monkeypatch, with_upstream):
    _patch_transport(monkeypatch, lambda request: httpx.Response(404, json={"detail": "нет"}))
    assert await upstream.fetch_public_repair("TOKEN123") is None


@pytest.mark.anyio
async def test_fetch_server_error_raises(monkeypatch, with_upstream):
    _patch_transport(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(upstream.UpstreamUnavailable):
        await upstream.fetch_public_repair("TOKEN123")


@pytest.mark.anyio
async def test_fetch_connection_error_raises(monkeypatch, with_upstream):
    def handler(request):
        raise httpx.ConnectError("нет связи с внутренним сервером")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(upstream.UpstreamUnavailable):
        await upstream.fetch_public_repair("TOKEN123")


@pytest.mark.anyio
async def test_fetch_without_upstream_raises(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PUBLIC_UPSTREAM_URL", "")
    with pytest.raises(upstream.UpstreamUnavailable):
        await upstream.fetch_public_repair("TOKEN123")


# --------------------------------------------------------------------------
# Страница и JSON на публичном сервере
# --------------------------------------------------------------------------
def test_page_renders_from_upstream(client, monkeypatch, with_upstream):
    async def fake_fetch(token):
        assert token == "TOKEN123"
        return PublicRepairOut.model_validate(PAYLOAD)

    monkeypatch.setattr(upstream, "fetch_public_repair", fake_fetch)
    r = client.get("/r/TOKEN123")
    assert r.status_code == 200
    assert "TV-ASG-2026-00001" in r.text
    assert "В работе" in r.text


def test_page_404_when_repair_missing(client, monkeypatch, with_upstream):
    async def fake_fetch(token):
        return None

    monkeypatch.setattr(upstream, "fetch_public_repair", fake_fetch)
    r = client.get("/r/TOKEN123")
    assert r.status_code == 404
    assert "Ремонт не найден" in r.text


def test_page_502_when_internal_server_down(client, monkeypatch, with_upstream):
    async def fake_fetch(token):
        raise upstream.UpstreamUnavailable("нет связи")

    monkeypatch.setattr(upstream, "fetch_public_repair", fake_fetch)
    r = client.get("/r/TOKEN123")
    assert r.status_code == 502
    # нельзя говорить клиенту, что ремонт «не найден», если связь просто пропала
    assert "Ремонт не найден" not in r.text


def test_json_is_proxied_from_upstream(client, monkeypatch, with_upstream):
    async def fake_fetch(token):
        return PublicRepairOut.model_validate(PAYLOAD)

    monkeypatch.setattr(upstream, "fetch_public_repair", fake_fetch)
    r = client.get("/api/public/r/TOKEN123")
    assert r.status_code == 200
    assert r.json()["number"] == "TV-ASG-2026-00001"


def test_json_502_when_internal_server_down(client, monkeypatch, with_upstream):
    async def fake_fetch(token):
        raise upstream.UpstreamUnavailable("нет связи")

    monkeypatch.setattr(upstream, "fetch_public_repair", fake_fetch)
    r = client.get("/api/public/r/TOKEN123")
    assert r.status_code == 502


def test_upstream_mode_does_not_need_db(client, monkeypatch, with_upstream):
    """Публичный сервер не открывает сессию БД на клиентском пути."""
    calls = []

    async def fake_fetch(token):
        return PublicRepairOut.model_validate(PAYLOAD)

    monkeypatch.setattr(upstream, "fetch_public_repair", fake_fetch)

    from app.db import session as db_session

    real_factory = db_session.async_session_factory

    def spy(*args, **kwargs):
        calls.append(1)
        return real_factory(*args, **kwargs)

    monkeypatch.setattr("app.webui.routes_public.async_session_factory", spy)
    assert client.get("/r/TOKEN123").status_code == 200
    assert calls == [], "страница клиента не должна обращаться к базе"
