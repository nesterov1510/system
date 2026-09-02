import uuid

PHONE_N = 7000000000


def _unique_phone():
    global PHONE_N
    PHONE_N += 1
    return f"+7999{PHONE_N}"


def _make_repair(client, headers, city_id, phone, key):
    r = client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": city_id,
            "client": {
                "full_name": "Удаляемый Клиент",
                "phone": phone,
                "consent_pdn": True,
                "consent_storage": True,
            },
            "device_type": "Телевизоры",
            "brand": "Samsung",
            "model": "UE55",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_operator_and_master_cannot_delete(client, operator_headers, master_headers, created_repair):
    for h in (operator_headers, master_headers):
        r = client.delete(f"/api/repairs/{created_repair['id']}", headers=h)
        assert r.status_code == 403
        r2 = client.delete(
            f"/api/repairs/clients/{created_repair['client_id']}", headers=h
        )
        assert r2.status_code == 403


def test_admin_deletes_repair_and_client(client, admin_headers, city_id):
    phone = _unique_phone()
    repair = _make_repair(
        client, admin_headers, city_id, phone, f"del-{uuid.uuid4()}"
    )
    # Удаляем ремонт
    r = client.delete(f"/api/repairs/{repair['id']}", headers=admin_headers)
    assert r.status_code == 200
    gone = client.get(f"/api/repairs/{repair['id']}", headers=admin_headers)
    assert gone.status_code == 404

    # Клиент остался (ремонт удалён, клиента прячем) — теперь удаляем клиента
    r2 = client.delete(
        f"/api/repairs/clients/{repair['client_id']}", headers=admin_headers
    )
    assert r2.status_code == 200
    names = client.get("/api/repairs/clients/list", headers=admin_headers).json()
    assert all(c["id"] != str(repair["client_id"]) for c in names)


def test_self_profile_update(client, admin_headers, city_id):
    email = f"profile-{uuid.uuid4().hex[:8]}@msb.local"
    created = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Имя Фамилия",
            "email": email,
            "password": "secret123",
            "role": "operator",
        },
    )
    assert created.status_code == 201, created.text
    me = client.post("/api/auth/login", json={"email": email, "password": "secret123"})
    headers = {"Authorization": f"Bearer {me.json()['access_token']}"}

    # Меняем имя/телефон/telegram
    up = client.patch(
        "/api/auth/me",
        headers=headers,
        json={"name": "Новое Имя", "phone": "+99361000000", "telegram": "@ivan_msb"},
    )
    assert up.status_code == 200
    assert up.json()["name"] == "Новое Имя"
    assert up.json()["telegram"] == "@ivan_msb"

    # Смена пароля без верного текущего -> 400
    bad = client.patch(
        "/api/auth/me",
        headers=headers,
        json={"current_password": "wrong", "new_password": "newsecret123"},
    )
    assert bad.status_code == 400

    # Смена пароля с верным текущим
    ok = client.patch(
        "/api/auth/me",
        headers=headers,
        json={"current_password": "secret123", "new_password": "newsecret123"},
    )
    assert ok.status_code == 200
    relogin = client.post(
        "/api/auth/login", json={"email": email, "password": "newsecret123"}
    )
    assert relogin.status_code == 200

    # email уже занят кем-то другим -> 409
    dup = client.patch(
        "/api/auth/me",
        headers=headers,
        json={"email": "admin@msb.local"},
    )
    assert dup.status_code == 409
