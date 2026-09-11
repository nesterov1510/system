"""QR на бланке должен вести на текущий UI (:8085), не на старый Next.js (:3030)."""
from types import SimpleNamespace

from app.core.config import normalize_public_base_url
from app.services.public_url import public_base_url, public_status_url


def test_normalize_rewrites_legacy_frontend_ports():
    assert (
        normalize_public_base_url("http://192.168.8.81:3030")
        == "http://192.168.8.81:8085"
    )
    assert normalize_public_base_url("http://localhost:3000") == "http://localhost:8085"
    assert (
        normalize_public_base_url("http://192.168.8.81:8085")
        == "http://192.168.8.81:8085"
    )
    assert normalize_public_base_url("http://example.com") == "http://example.com"
    assert normalize_public_base_url("") == "http://localhost:8085"
    assert normalize_public_base_url("192.168.8.81:3030") == "http://192.168.8.81:8085"


def _req(host: str, scheme: str = "http"):
    hostname, _, port = host.partition(":")
    return SimpleNamespace(
        headers={"host": host},
        url=SimpleNamespace(
            scheme=scheme,
            hostname=hostname,
            port=int(port) if port else None,
        ),
    )


def test_public_base_url_uses_request_host_and_app_port(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "PUBLIC_BASE_URL", "http://192.168.8.81:3030")
    assert public_base_url(_req("192.168.8.81:3030")) == "http://192.168.8.81:8085"


def test_public_base_url_keeps_lan_when_operator_on_localhost(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "PUBLIC_BASE_URL", "http://192.168.8.81:8085")
    assert public_base_url(_req("localhost:8085")) == "http://192.168.8.81:8085"


def test_public_status_url_is_client_page():
    url = public_status_url("tok123")
    assert url.endswith("/r/tok123")
    assert ":3030" not in url
    assert ":3000" not in url
