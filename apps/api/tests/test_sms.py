"""Тесты SMS-уведомлений: авто-SMS мастеру при назначении + «Ремонт закончен»."""

import asyncio

from app.services.sms import (
    _gateway_phone,
    build_master_sms,
    build_ready_sms,
    send_master_assignment_sms,
)


# --- чистые функции (без сети) -------------------------------------------------

def test_gateway_phone_normalization():
    assert _gateway_phone("+993 71 693009") == "+99371693009"
    assert _gateway_phone("+79998887766") == "+79998887766"
    assert _gateway_phone("99371693009") == "+99371693009"
    assert _gateway_phone("") == ""


def _mk_repair(**over):
    class _C:
        def __init__(self, name, phone):
            self.full_name = name
            self.phone = phone

    class _R:
        pass

    r = _R()
    r.number = over.get("number", "TV-ASG-2026-00001")
    r.device_type = over.get("device_type", "ТВ")
    r.brand = over.get("brand", "Samsung")
    r.model = over.get("model", "UE55")
    r.serial = over.get("serial", None)
    r.fault_client = over.get("fault_client", "не включается")
    r.eta_days = over.get("eta_days", 3)
    r.client = _C(over.get("client_name", "Иван"), over.get("client_phone", "+99361000001"))
    return r


def test_master_sms_template_contains_repair_data():
    r = _mk_repair()
    text = build_master_sms("Мастер Анна", r)
    assert "TV-ASG-2026-00001" in text
    assert "Samsung UE55" in text
    assert "не включается" in text
    assert "Иван" in text


def test_ready_sms_template():
    r = _mk_repair()
    text = build_ready_sms(r)
    assert r.number in text
    assert "Иван" in text
    assert "готова к выдаче" in text or "отремонтирован" in text


# --- «Ремонт закончен» endpoint -------------------------------------------------

def _mk_repair_via_api(client, headers, city_id, key, name="Клиент SMS", phone="+993 71 111222"):
    r = client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": city_id,
            "client": {"full_name": name, "phone": phone, "consent_pdn": True},
            "device_type": "ТВ",
            "brand": "Samsung",
            "model": "UE55",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_finish_repair_marks_ready_and_returns_sms(
    client, operator_headers, city_id
):
    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-finish-1")
    r = client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repair"]["status"] == "Готово к выдаче"
    assert body["repair"]["ready_at"] is not None
    assert body["sms"]["to"] == "+993 71 111222"
    assert repair["number"] in body["sms"]["text"]


def test_finish_forbidden_for_master(
    client, admin_headers, operator_headers, master_headers, city_id
):
    # Мастер из conftest (роль master). Найдём его id.
    users = client.get("/api/admin/users", headers=admin_headers).json()
    master = next(u for u in users if u["email"] == "master@msb.local")

    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-finish-2")
    # Назначаем мастера — он получает доступ к ремонту.
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"master_ids": [master["id"]]},
    )
    assert r.status_code == 200, r.text
    # Доступ у мастера есть, но «Ремонт закончен» — только админ/оператор.
    assert client.get(f"/api/repairs/{repair['id']}", headers=master_headers).status_code == 200
    assert client.post(f"/api/repairs/{repair['id']}/finish", headers=master_headers).status_code == 403


def test_finish_sms_send(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-finish-3")
    sent = {}
    async def _fake_send(phone, text):
        sent["phone"] = phone
        sent["text"] = text
        return {"ok": True, "detail": "http_200"}
    monkeypatch.setattr("app.routers.repairs.send_sms", _fake_send)

    r = client.post(
        f"/api/repairs/{repair['id']}/finish-sms",
        headers=operator_headers,
        json={"text": "Мой текст клиенту"},
    )
    assert r.status_code == 200, r.text
    assert sent["phone"].replace(" ", "") == "+99371111222"
    assert sent["text"] == "Мой текст клиенту"
    # Зафиксировано событие в истории.
    detail = client.get(f"/api/repairs/{repair['id']}", headers=operator_headers).json()
    types = [e["type"] for e in detail["events"]]
    assert "notify" in types


def test_finish_sms_send_failure(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-finish-4")
    async def _fake_fail(phone, text):
        return {"ok": False, "detail": "http_500"}
    monkeypatch.setattr("app.routers.repairs.send_sms", _fake_fail)
    r = client.post(
        f"/api/repairs/{repair['id']}/finish-sms",
        headers=operator_headers,
        json={"text": "текст"},
    )
    assert r.status_code == 502


# --- авто-SMS мастеру при назначении --------------------------------------------

def test_auto_sms_to_master_on_assignment(
    client, admin_headers, operator_headers, city_id, monkeypatch
):
    # Мастер с телефоном.
    master = client.post(
        "/api/admin/users", headers=admin_headers,
        json={"name": "Мастер SMS", "email": "mastersms@msb.local",
              "password": "pass123", "role": "master", "phone": "+993 62 333444"},
    ).json()

    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-assign-1")

    calls = []
    async def _fake_sms(m, rp):
        calls.append((str(m.id), str(rp.id)))
        return {"ok": True}
    monkeypatch.setattr("app.routers.repairs.send_master_assignment_sms", _fake_sms)

    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"master_ids": [master["id"]]},
    )
    assert r.status_code == 200, r.text
    assert (master["id"], repair["id"]) in calls


def test_master_sms_skipped_without_phone(monkeypatch):
    """send_master_assignment_sms не звонит на шлюз, если у мастера нет номера."""
    class _M:
        name = "Мастер"
        phone = None
    hit = []
    async def _fake_send(phone, text):
        hit.append(phone)
        return {"ok": True}
    monkeypatch.setattr("app.services.sms.send_sms", _fake_send)

    res = asyncio.run(send_master_assignment_sms(_M(), _mk_repair()))
    assert res["ok"] is False
    assert hit == []


def test_master_sms_sent_with_phone(monkeypatch):
    """При наличии номера шлём SMS по шаблону на нормализованный телефон."""
    class _M:
        name = "Мастер Анна"
        phone = "+993 62 333444"
    sent = {}
    async def _fake_send(phone, text):
        sent["phone"] = phone
        sent["text"] = text
        return {"ok": True}
    monkeypatch.setattr("app.services.sms.send_sms", _fake_send)

    res = asyncio.run(send_master_assignment_sms(_M(), _mk_repair()))
    assert res["ok"] is True
    # send_sms сам приводит номер к виду шлюза (+993..., без пробелов); сюда
    # передаётся как в БД.
    assert sent["phone"] == "+993 62 333444"
    assert "Мастер Анна" in sent["text"]
    assert "TV-ASG-2026-00001" in sent["text"]
