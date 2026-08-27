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
    with TestClient(app) as c:
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
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def master_headers(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "master@msb.local", "password": "master123"},
    )
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def city_id(client, admin_headers):
    r = client.get("/api/lookups/cities", headers=admin_headers)
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
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()
