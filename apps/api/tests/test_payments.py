def test_add_payment(client, admin_headers, created_repair):
    r = client.post(
        f"/api/repairs/{created_repair['id']}/payments",
        headers=admin_headers,
        json={"amount": 1500, "method": "card"},
    )
    assert r.status_code == 201
    assert r.json()["amount"] == 1500
    assert r.json()["method"] == "card"


def test_list_payments(client, admin_headers, created_repair):
    r = client.get(f"/api/repairs/{created_repair['id']}/payments", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_refund_allowed_for_operator(client, operator_headers, created_repair):
    # operator adds payment
    r = client.post(
        f"/api/repairs/{created_repair['id']}/payments",
        headers=operator_headers,
        json={"amount": 500, "method": "cash"},
    )
    pid = r.json()["id"]
    # Оператор имеет всё, кроме аналитики — возврат (удаление платежа) разрешён.
    r2 = client.delete(f"/api/payments/{pid}", headers=operator_headers)
    assert r2.status_code == 200


def test_revenue_in_overview(client, admin_headers):
    r = client.get("/api/stats/overview", headers=admin_headers)
    assert r.status_code == 200
    assert "revenue" in r.json()
    assert r.json()["revenue"] >= 0
