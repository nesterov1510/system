def test_admin_user_crud(client, admin_headers, operator_headers):
    # Create
    r = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Новичок",
            "email": "newbie@msb.local",
            "password": "newbie123",
            "role": "operator",
        },
    )
    assert r.status_code == 201
    uid = r.json()["id"]

    # Duplicate email -> 409
    r2 = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"name": "Дубль", "email": "newbie@msb.local", "password": "x12345", "role": "operator"},
    )
    assert r2.status_code == 409

    # Update (role + password)
    r3 = client.patch(
        f"/api/admin/users/{uid}",
        headers=admin_headers,
        json={"role": "master", "password": "newpass123"},
    )
    assert r3.status_code == 200
    assert r3.json()["role"] == "master"

    # New password works
    r4 = client.post(
        "/api/auth/login",
        json={"email": "newbie@msb.local", "password": "newpass123"},
    )
    assert r4.status_code == 200

    # Deactivate
    r5 = client.delete(f"/api/admin/users/{uid}", headers=admin_headers)
    assert r5.status_code == 200
    assert r5.json()["ok"] is True

    # Deactivated cannot login
    r6 = client.post(
        "/api/auth/login",
        json={"email": "newbie@msb.local", "password": "newpass123"},
    )
    assert r6.status_code in (401, 403)


def test_operator_cannot_manage_users(client, operator_headers):
    r = client.get("/api/admin/users", headers=operator_headers)
    assert r.status_code == 403
    r2 = client.post(
        "/api/admin/users",
        headers=operator_headers,
        json={"name": "X", "email": "x@x.x", "password": "x12345", "role": "operator"},
    )
    assert r2.status_code == 403


def test_cannot_deactivate_self(client, admin_headers):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    admin = next(u for u in users if u["role"] == "admin")
    r = client.delete(f"/api/admin/users/{admin['id']}", headers=admin_headers)
    assert r.status_code == 400
