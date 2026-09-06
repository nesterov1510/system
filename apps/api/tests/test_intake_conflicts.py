"""Приёмка: конфликты уникальности и «воскрешение» удалённого клиента.

Боевая ошибка: мастер принимает технику и получает «Не удалось выделить номер
ремонта — приёмку пытаются оформить одновременно». В логе при этом пять попыток
с `duplicate key value violates unique constraint "ix_clients_phone_norm"`, то
есть конфликт вообще не в номере ремонта: клиент с таким телефоном уже есть, но
он мягко удалён (`deleted_at`), поиск его не видит, INSERT падает, а retry-цикл
трактует любую IntegrityError как конфликт номера.

Здесь же — гонка двух операторов на одном номере ремонта: повтор обязан
доходить до конца, а не падать на «протухших» после rollback ORM-объектах.
"""
import uuid

from sqlalchemy.exc import IntegrityError

import app.routers.repairs as repairs_router
from app.db.conflicts import CLIENT_PHONE, NUMBER, OTHER, classify


# ---------------------------------------------------------------------------
# Заготовки IntegrityError: asyncpg отдаёт имя ограничения атрибутом,
# SQLite — только текстом сообщения. Классификатор обязан понимать оба.
# ---------------------------------------------------------------------------
class _PgUniqueViolation(Exception):
    def __init__(self, constraint_name: str):
        super().__init__(
            f'duplicate key value violates unique constraint "{constraint_name}"'
        )
        self.constraint_name = constraint_name


def _pg_integrity(constraint: str) -> IntegrityError:
    return IntegrityError("INSERT INTO ...", {}, _PgUniqueViolation(constraint))


def _sqlite_integrity(text: str) -> IntegrityError:
    return IntegrityError("INSERT INTO ...", {}, Exception(text))


def _mk_repair(client, headers, city_id, key, phone="+993 61 770011", name="Клиент Приёмка"):
    return client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": city_id,
            "client": {"full_name": name, "phone": phone, "consent_pdn": True},
            "device_type": "Телевизоры",
            "brand": "Samsung",
            "fault_client": "не включается",
        },
    )


def _lookup(client, headers, phone):
    r = client.get("/api/repairs/clients/lookup", headers=headers, params={"phone": phone})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Классификация конфликта
# ---------------------------------------------------------------------------
def test_classify_pg_number_conflict():
    assert classify(_pg_integrity("ix_repairs_number")) == NUMBER


def test_classify_pg_client_phone_conflict():
    assert classify(_pg_integrity("ix_clients_phone_norm")) == CLIENT_PHONE


def test_classify_sqlite_number_conflict():
    assert classify(_sqlite_integrity("UNIQUE constraint failed: repairs.number")) == NUMBER


def test_classify_sqlite_client_phone_conflict():
    assert classify(
        _sqlite_integrity("UNIQUE constraint failed: clients.phone_norm")
    ) == CLIENT_PHONE


def test_classify_unknown_conflict():
    assert classify(_pg_integrity("uq_repair_master")) == OTHER
    assert classify(_sqlite_integrity("FOREIGN KEY constraint failed")) == OTHER


# ---------------------------------------------------------------------------
# Удалённый клиент не должен блокировать приёмку навсегда
# ---------------------------------------------------------------------------
def test_intake_after_client_soft_delete_succeeds(client, admin_headers, operator_headers, city_id):
    phone = "+993 61 771122"
    first = _mk_repair(client, operator_headers, city_id, "conf-1", phone=phone)
    assert first.status_code == 201, first.text
    client_id = first.json()["client_id"]

    deleted = client.delete(f"/api/repairs/clients/{client_id}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    assert _lookup(client, operator_headers, phone)["found"] is False

    # Тот же номер телефона, новый ремонт: раньше — 409 «не удалось выделить
    # номер ремонта», теперь приёмка проходит.
    second = _mk_repair(client, operator_headers, city_id, "conf-2", phone=phone)
    assert second.status_code == 201, second.text
    # Клиент не задублировался — ремонт повис на прежней карточке.
    assert second.json()["client_id"] == client_id
    assert _lookup(client, operator_headers, phone)["found"] is True


def test_deleted_client_is_restored_and_keeps_history(client, admin_headers, operator_headers, city_id):
    phone = "+993 61 771133"
    first = _mk_repair(client, operator_headers, city_id, "conf-3", phone=phone, name="Старое Имя")
    assert first.status_code == 201, first.text
    body = first.json()
    client_id = body["client_id"]
    old_number = body["number"]

    assert client.delete(f"/api/repairs/clients/{client_id}", headers=admin_headers).status_code == 200

    second = _mk_repair(client, operator_headers, city_id, "conf-4", phone=phone, name="Новое Имя")
    assert second.status_code == 201, second.text
    assert second.json()["client_id"] == client_id

    found = _lookup(client, operator_headers, phone)
    assert found["found"] is True and found["multiple"] is False
    # История не распалась: оба ремонта на одном клиенте.
    numbers = {r["number"] for r in found["repairs"]}
    assert old_number in numbers and second.json()["number"] in numbers
    # Имя не перезаписывается молча (расхождение фиксируется в аудите).
    assert found["client"]["full_name"] == "Старое Имя"


def test_client_restore_is_audited(client, admin_headers, operator_headers, city_id):
    phone = "+993 61 771144"
    first = _mk_repair(client, operator_headers, city_id, "conf-5", phone=phone)
    assert first.status_code == 201, first.text
    client_id = first.json()["client_id"]
    assert client.delete(f"/api/repairs/clients/{client_id}", headers=admin_headers).status_code == 200

    second = _mk_repair(client, operator_headers, city_id, "conf-6", phone=phone)
    assert second.status_code == 201, second.text

    rows = client.get(
        "/api/admin/audit",
        headers=admin_headers,
        params={"action": "client.restore", "entity_id": client_id},
    )
    assert rows.status_code == 200, rows.text
    restores = rows.json()
    assert restores, "восстановление клиента не попало в журнал аудита"
    assert restores[0]["meta"]["phone_norm"] == "99361771144"
    assert restores[0]["entity"] == "client"


def test_operator_cannot_delete_client_but_intake_still_works(client, operator_headers, city_id):
    """Удаление клиента — только админ; на приёмку это не влияет."""
    phone = "+993 61 771155"
    first = _mk_repair(client, operator_headers, city_id, "conf-7", phone=phone)
    assert first.status_code == 201, first.text
    r = client.delete(f"/api/repairs/clients/{first.json()['client_id']}", headers=operator_headers)
    assert r.status_code == 403

    second = _mk_repair(client, operator_headers, city_id, "conf-8", phone=phone)
    assert second.status_code == 201, second.text


# ---------------------------------------------------------------------------
# Retry-цикл: повторять только то, что имеет смысл повторять
# ---------------------------------------------------------------------------
def test_number_conflict_is_retried_and_succeeds(client, operator_headers, city_id, monkeypatch):
    """Конфликт номера ремонта — настоящая гонка: вторая попытка обязана пройти."""
    original = repairs_router._persist_repair
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _pg_integrity("ix_repairs_number")
        return await original(*args, **kwargs)

    monkeypatch.setattr(repairs_router, "_persist_repair", flaky)

    r = _mk_repair(client, operator_headers, city_id, f"conf-retry-{uuid.uuid4().hex[:8]}")
    assert r.status_code == 201, r.text
    assert calls["n"] == 2
    assert r.json()["number"]


def test_client_phone_conflict_is_not_blamed_on_repair_number(
    client, operator_headers, city_id, monkeypatch
):
    """Если упёрлись в телефон клиента — текст ошибки не должен врать про номер."""
    async def always_client_conflict(*args, **kwargs):
        raise _pg_integrity("ix_clients_phone_norm")

    monkeypatch.setattr(repairs_router, "_persist_repair", always_client_conflict)

    r = _mk_repair(client, operator_headers, city_id, f"conf-phone-{uuid.uuid4().hex[:8]}")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"].lower()
    assert "номер ремонта" not in detail
    assert "клиент" in detail


def test_unknown_integrity_error_is_not_retried(client, operator_headers, city_id, monkeypatch):
    """Бессмысленно пять раз повторять запрос, который падает по другой причине."""
    calls = {"n": 0}

    async def always_other(*args, **kwargs):
        calls["n"] += 1
        raise _pg_integrity("uq_repair_master")

    monkeypatch.setattr(repairs_router, "_persist_repair", always_other)

    r = _mk_repair(client, operator_headers, city_id, f"conf-other-{uuid.uuid4().hex[:8]}")
    assert r.status_code == 409, r.text
    assert calls["n"] == 1


def test_retry_does_not_duplicate_client(client, operator_headers, city_id, monkeypatch):
    """После отката и повтора клиент остаётся один (без «висящих» записей)."""
    original = repairs_router._persist_repair
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _sqlite_integrity("UNIQUE constraint failed: repairs.number")
        return await original(*args, **kwargs)

    monkeypatch.setattr(repairs_router, "_persist_repair", flaky)
    phone = "+993 61 771166"
    r = _mk_repair(
        client, operator_headers, city_id, f"conf-leak-{uuid.uuid4().hex[:8]}", phone=phone
    )
    assert r.status_code == 201, r.text

    found = _lookup(client, operator_headers, phone)
    assert found["found"] is True
    assert found.get("multiple") is not True, f"клиент задублировался после retry: {found}"


def test_phone_change_tells_that_clash_is_a_deleted_client(
    client, admin_headers, operator_headers, city_id
):
    """«Номер занят» должен объяснять, что карточка удалена, иначе админ в тупике."""
    deleted_phone = "+993 61 771177"
    first = _mk_repair(client, admin_headers, city_id, "conf-9", phone=deleted_phone)
    assert first.status_code == 201, first.text
    deleted_client_id = first.json()["client_id"]
    assert client.delete(
        f"/api/repairs/clients/{deleted_client_id}", headers=admin_headers
    ).status_code == 200

    other = _mk_repair(client, operator_headers, city_id, "conf-10", phone="+993 61 771188")
    assert other.status_code == 201, other.text
    other_client_id = other.json()["client_id"]

    r = client.patch(
        f"/api/repairs/clients/{other_client_id}",
        headers=admin_headers,
        json={"phone": deleted_phone},
    )
    assert r.status_code == 409, r.text
    assert "удалена" in r.json()["detail"]
