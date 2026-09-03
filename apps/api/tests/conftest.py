import os
import pathlib

# Must be set BEFORE importing app modules (settings is cached at import).
_DB = pathlib.Path("./test_msb.db")
if _DB.exists():
    _DB.unlink()

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_msb.db"
os.environ["SECRET_KEY"] = "test_secret_key_" + "x" * 40
os.environ["STORAGE_MODE"] = "local"
os.environ["UPLOAD_DIR"] = "./test_uploads"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """Start a clean test app and add only test fixtures, never production seed data."""
    with TestClient(app) as c:
        admin_login = c.post(
            "/api/auth/login",
            json={"email": "admin@msb.local", "password": "admin123"},
        )
        assert admin_login.status_code == 200, admin_login.text
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # The production seed intentionally creates only the admin. Additional
        # roles and catalog entries belong here, exclusively in the test DB.
        for user in (
            {
                "name": "Тестовый оператор",
                "email": "operator@msb.local",
                "password": "operator123",
                "role": "operator",
            },
            {
                "name": "Тестовый мастер",
                "email": "master@msb.local",
                "password": "master123",
                "role": "master",
            },
        ):
            response = c.post("/api/admin/users", headers=admin_headers, json=user)
            assert response.status_code == 201, response.text

        part = c.post(
            "/api/parts",
            headers=admin_headers,
            json={
                "name": "Тестовая деталь",
                "sku": "TEST-PART-001",
                "category": "Компоненты",
                "stock_qty": 10,
                "min_stock": 2,
            },
        )
        assert part.status_code == 201, part.text

        price = c.post(
            "/api/prices",
            headers=admin_headers,
            json={
                "device_type": "ТВ",
                "brand": "Samsung",
                "fault": "не включается",
                "price_min": 350,
                "price_max": 600,
                "price_avg": 450,
                "typical_days": 5,
                "source": "test",
            },
        )
        assert price.status_code == 201, price.text

        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@msb.local", "password": "admin123"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def operator_headers(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "operator@msb.local", "password": "operator123"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def master_headers(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "master@msb.local", "password": "master123"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def city_id(client, admin_headers):
    r = client.get("/api/lookups/cities", headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


@pytest.fixture(scope="session")
def created_repair(client, operator_headers, city_id):
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "test-repair-1"},
        json={
            "city_id": city_id,
            "client": {
                "full_name": "Тест Тестов",
                "phone": "+79998887766",
                "consent_pdn": True,
                "consent_storage": True,
            },
            "device_type": "ТВ",
            "brand": "Samsung",
            "model": "UE55",
            "complectation": {
                "items": ["Пульт", "Шнур питания", "Ножки"],
            },
            "condition_notes": "Линии на экране, Царапины, Скол корпуса",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()
