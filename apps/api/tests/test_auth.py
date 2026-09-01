def test_login_success(client, admin_headers):
    assert "Authorization" in admin_headers


def test_login_failure(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@msb.local", "password": "wrong"},
    )
    assert r.status_code == 401


def test_me(client, admin_headers):
    r = client.get("/api/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_me_unauthorized(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_admin_only_for_operator(client, operator_headers):
    r = client.get("/api/admin/cities", headers=operator_headers)
    assert r.status_code == 403
