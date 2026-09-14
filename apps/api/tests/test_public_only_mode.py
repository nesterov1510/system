"""Режим PUBLIC_ONLY: наружу отдаётся только то, что видит клиент.

Тот же код поднимается вторым экземпляром с PUBLIC_ONLY=true на адресе,
который смотрит в интернет. Он обязан отдать публичную страницу ремонта
/r/{token}, её JSON, CSS страницы и /health — и 404 на всё остальное
(приёмку, админку, справочники, /docs, внутренние статику и медиа).
"""
import pytest


@pytest.fixture()
def public_only():
    """Включить PUBLIC_ONLY на время теста."""
    from app.main import settings

    old = settings.PUBLIC_ONLY
    settings.PUBLIC_ONLY = True
    yield
    settings.PUBLIC_ONLY = old


def _token(created_repair):
    """Токен берём из фикстуры: в режиме PUBLIC_ONLY API уже закрыт."""
    return created_repair["public_token"]


# --------------------------------------------------------------------------
# Обычный режим ничего не теряет
# --------------------------------------------------------------------------
def test_default_mode_serves_everything(client, admin_headers):
    from app.main import settings

    assert settings.PUBLIC_ONLY is False
    r = client.post(
        "/login",
        data={"email": "admin@msb.local", "password": "admin123", "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert client.get("/repairs", cookies=dict(r.cookies)).status_code == 200
    assert client.get("/api/repairs", headers=admin_headers).status_code == 200


# --------------------------------------------------------------------------
# PUBLIC_ONLY: клиентское работает
# --------------------------------------------------------------------------
def test_public_page_and_its_assets_are_served(client, admin_headers, created_repair, public_only):
    token = _token(created_repair)
    page = client.get(f"/r/{token}")
    assert page.status_code == 200
    assert created_repair["number"] in page.text

    assert client.get("/static/msb/base.css").status_code == 200
    assert client.get(f"/api/public/r/{token}").status_code == 200
    assert client.get("/health").status_code == 200


def test_public_page_does_not_leak_internal_data(client, admin_headers, created_repair, public_only):
    token = _token(created_repair)
    body = client.get(f"/r/{token}").text
    for secret in ("admin@msb.local", "master_payout", "Запчасти", "price_max"):
        assert secret not in body, secret


# --------------------------------------------------------------------------
# PUBLIC_ONLY: всё служебное закрыто
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/login",
        "/repairs",
        "/repairs/new",
        "/clients",
        "/parts",
        "/prices",
        "/callcenter",
        "/chat",
        "/dashboard",
        "/dashboard/finance",
        "/profile",
        "/notifications",
        "/admin/users",
        "/admin/settings",
        "/admin/logs",
        "/ui/layout",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/static/msb/repair.css",
        "/static/msb/layout.js",
        "/static/msb/priemka/phone.js",
        "/media/anything.jpg",
        "/api/repairs",
        "/api/admin/users",
        "/api/auth/login",
        "/api/parts",
        "/api/stats/overview",
    ],
)
def test_internal_paths_return_404(client, path, public_only):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 404, (path, r.status_code)
    # снаружи не должно быть видно, что раздел вообще существует
    assert r.text.strip() == "Not Found"


def test_internal_posts_are_closed_too(client, admin_headers, created_repair, public_only):
    r = client.post(
        "/login",
        data={"email": "admin@msb.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert r.status_code == 404
    r = client.post(
        f"/repairs/{created_repair['id']}/status",
        data={"status": "Завершён"},
        follow_redirects=False,
    )
    assert r.status_code == 404
    r = client.post("/ui/layout", data={"page": "repair_card", "order": "log", "next": "/repairs"},
                    follow_redirects=False)
    assert r.status_code == 404


def test_wrong_token_is_not_a_leak(client, public_only):
    r = client.get("/r/несуществующий-токен")
    assert r.status_code == 404


# --------------------------------------------------------------------------
# QR клиента ведёт на публичный адрес, а не во внутреннюю сеть
# --------------------------------------------------------------------------
def test_qr_points_to_client_base_url_when_set():
    from app.core.config import settings
    from app.services.public_url import public_status_url

    old = settings.CLIENT_BASE_URL
    try:
        settings.CLIENT_BASE_URL = "https://status.msb.tm"
        assert public_status_url("TOKEN123") == "https://status.msb.tm/r/TOKEN123"
        # хвост и порт нормализуются
        settings.CLIENT_BASE_URL = "https://status.msb.tm/"
        assert public_status_url("TOKEN123") == "https://status.msb.tm/r/TOKEN123"
    finally:
        settings.CLIENT_BASE_URL = old


def test_qr_keeps_old_behaviour_without_client_base_url():
    from app.core.config import settings
    from app.services.public_url import public_status_url

    old = settings.CLIENT_BASE_URL
    try:
        settings.CLIENT_BASE_URL = ""
        url = public_status_url("TOKEN123")
        assert url.endswith("/r/TOKEN123")
        assert "status.msb.tm" not in url
    finally:
        settings.CLIENT_BASE_URL = old


def test_internal_links_stay_on_internal_origin():
    """CLIENT_BASE_URL касается только клиентской страницы."""
    from app.core.config import settings
    from app.services.public_url import public_repair_url, public_status_url

    old = settings.CLIENT_BASE_URL
    try:
        settings.CLIENT_BASE_URL = "https://status.msb.tm"
        assert public_status_url("T").startswith("https://status.msb.tm/")
        assert "status.msb.tm" not in public_repair_url("uuid-1")
    finally:
        settings.CLIENT_BASE_URL = old


def test_printed_blank_uses_client_base_url(client, admin_headers, created_repair):
    """Бланк и этикетка строят QR той же функцией, что проверена выше."""
    import inspect

    from app.routers import prints
    from app.core.config import settings

    src = inspect.getsource(prints)
    assert "public_status_url(repair.public_token, request)" in src
    old = settings.CLIENT_BASE_URL
    try:
        settings.CLIENT_BASE_URL = "https://status.msb.tm"
        ctx_url = prints.public_status_url(created_repair["public_token"], None)
        assert ctx_url == f"https://status.msb.tm/r/{created_repair['public_token']}"
    finally:
        settings.CLIENT_BASE_URL = old
