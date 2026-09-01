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


def test_operator_can_access_admin_management(client, operator_headers):
    # Оператор имеет всё, кроме аналитики — управление точками разрешено.
    r = client.get("/api/admin/cities", headers=operator_headers)
    assert r.status_code == 200


def test_analytics_admin_only(client, operator_headers, master_headers):
    # Аналитика (статистика/AI) закрыта для оператора и мастера.
    for headers in (operator_headers, master_headers):
        r = client.get("/api/stats/overview", headers=headers)
        assert r.status_code == 403
        r2 = client.post(
            "/api/ai/predict-eta", headers=headers, json={"device_type": "ТВ"}
        )
        assert r2.status_code == 403
