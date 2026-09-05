"""Правка марки/модели/серийного номера уже принятого ремонта.

Операторы ошибаются при приёмке, а пересоздавать ремонт нельзя: теряется номер,
этикетка уже наклеена. Поэтому паспорт техники правится через PATCH — но только
старшими ролями и со следом в истории ремонта и в журнале аудита.
"""


def _mk_repair(client, headers, city_id, key, brand="Samsung", model="UE55", serial="SN-1"):
    r = client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": city_id,
            "client": {
                "full_name": "Клиент Техника",
                "phone": "+993 61 220022",
                "consent_pdn": True,
            },
            "device_type": "Телевизоры",
            "brand": brand,
            "model": model,
            "serial": serial,
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_operator_can_fix_brand_and_model(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-1")
    assert repair["brand"] == "Samsung"

    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"brand": "LG", "model": "43UP7500"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["brand"] == "LG"
    assert body["model"] == "43UP7500"
    # Серийник не трогали — остался прежним.
    assert body["serial"] == "SN-1"


def test_device_change_is_written_to_history(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-2")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"brand": "Xiaomi", "serial": "SN-999"},
    )
    assert r.status_code == 200, r.text

    events = [e for e in r.json()["events"] if e["type"] == "device"]
    assert len(events) == 1
    message = events[0]["data"]["message"]
    assert "Samsung" in message and "Xiaomi" in message
    assert "SN-1" in message and "SN-999" in message
    changes = events[0]["data"]["changes"]
    assert changes["brand"] == {"from": "Samsung", "to": "Xiaomi"}
    assert changes["serial"] == {"from": "SN-1", "to": "SN-999"}


def test_device_change_is_audited(client, admin_headers, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-3")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"model": "QE55Q60"},
    )
    assert r.status_code == 200, r.text

    audit_rows = client.get("/api/admin/audit", headers=admin_headers).json()
    items = audit_rows.get("items", audit_rows) if isinstance(audit_rows, dict) else audit_rows
    mine = [
        a
        for a in items
        if a.get("action") == "repair.device" and str(a.get("entity_id")) == repair["id"]
    ]
    assert mine, "правка техники не попала в журнал аудита"
    assert mine[0]["meta"]["changes"]["model"]["to"] == "QE55Q60"


def test_master_cannot_edit_device_info(client, admin_headers, operator_headers, master_headers, city_id):
    """Мастер видит ремонт, но паспорт техники не правит (как на сервере)."""
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-4")
    users = client.get("/api/admin/users", headers=admin_headers).json()
    master = next(u for u in users if u["email"] == "master@msb.local")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"master_ids": [master["id"]]},
    )
    assert r.status_code == 200, r.text
    # Доступ к ремонту у мастера есть…
    assert client.get(f"/api/repairs/{repair['id']}", headers=master_headers).status_code == 200

    r = client.patch(
        f"/api/repairs/{repair['id']}", headers=master_headers, json={"brand": "Подменено"}
    )
    assert r.status_code == 403
    assert "администратор" in r.json()["detail"].lower()

    # И значение не изменилось.
    after = client.get(f"/api/repairs/{repair['id']}", headers=operator_headers).json()
    assert after["brand"] == "Samsung"


def test_manager_can_edit_device_info(client, admin_headers, operator_headers, city_id):
    manager = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Менеджер Техника",
            "email": "manager-dev@msb.local",
            "password": "manager123",
            "role": "manager",
        },
    )
    assert manager.status_code == 201, manager.text
    login = client.post(
        "/api/auth/login",
        json={"email": "manager-dev@msb.local", "password": "manager123"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-5")
    r = client.patch(
        f"/api/repairs/{repair['id']}", headers=headers, json={"brand": "Sony"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["brand"] == "Sony"


def test_brand_cannot_be_empty(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-6")
    r = client.patch(
        f"/api/repairs/{repair['id']}", headers=operator_headers, json={"brand": "   "}
    )
    assert r.status_code == 422, r.text

    # А модель и серийник очистить можно (техника без модели — обычное дело).
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"model": "", "serial": ""},
    )
    assert r.status_code == 200, r.text
    assert r.json()["model"] is None
    assert r.json()["serial"] is None


def test_device_values_are_trimmed(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-7")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"brand": "  Samsung  ", "model": " UE\t55 "},
    )
    assert r.status_code == 200, r.text
    assert r.json()["brand"] == "Samsung"
    assert r.json()["model"] == "UE 55"


def test_too_long_brand_rejected(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-8")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"brand": "X" * 129},
    )
    assert r.status_code == 422, r.text


def test_unchanged_device_fields_do_not_create_event(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-9")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"brand": "Samsung", "model": "UE55", "serial": "SN-1"},
    )
    assert r.status_code == 200, r.text
    assert [e for e in r.json()["events"] if e["type"] == "device"] == []


def test_device_edit_keeps_number_and_photos(client, operator_headers, city_id):
    """Правка марки — не пересоздание ремонта: номер и история остаются."""
    repair = _mk_repair(client, operator_headers, city_id, "dev-edit-10")
    client.post(f"/api/repairs/{repair['id']}/events", headers=operator_headers,
                json={"type": "comment", "message": "клиент звонил"})

    r = client.patch(
        f"/api/repairs/{repair['id']}", headers=operator_headers, json={"brand": "TCL"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == repair["id"]
    assert r.json()["number"] == repair["number"]
    assert r.json()["public_token"] == repair["public_token"]
    assert any(e["type"] == "comment" for e in r.json()["events"])
