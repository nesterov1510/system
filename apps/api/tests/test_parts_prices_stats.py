def test_list_parts(client, admin_headers):
    r = client.get("/api/parts", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_parts_crud(client, admin_headers):
    r = client.post(
        "/api/parts",
        headers=admin_headers,
        json={"name": "Тестовая деталь", "category": "Компоненты", "stock_qty": 10},
    )
    assert r.status_code == 201
    part = r.json()
    assert part["stock_qty"] == 10

    r2 = client.patch(
        f"/api/parts/{part['id']}", headers=admin_headers, json={"stock_qty": 7}
    )
    assert r2.json()["stock_qty"] == 7


def test_add_part_to_repair_debits_stock(client, admin_headers, created_repair):
    parts = client.get("/api/parts", headers=admin_headers).json()
    part = parts[0]
    before = part["stock_qty"]

    r = client.post(
        f"/api/repairs/{created_repair['id']}/parts",
        headers=admin_headers,
        json={"part_id": part["id"], "qty": 1},
    )
    assert r.status_code == 201
    assert r.json()["part_name"] == part["name"]

    after = client.get("/api/parts", headers=admin_headers).json()
    new_stock = next(p["stock_qty"] for p in after if p["id"] == part["id"])
    assert new_stock == max(before - 1, 0)


def test_operator_cannot_edit_parts(client, operator_headers):
    r = client.post(
        "/api/parts",
        headers=operator_headers,
        json={"name": "Запрещено", "stock_qty": 1},
    )
    assert r.status_code == 403


def test_analytics_closed_to_operator_and_master(
    client, operator_headers, master_headers
):
    # Аналитика (статистика и AI-прогнозы) — только админ/менеджер.
    for h in (operator_headers, master_headers):
        r = client.get("/api/stats/overview", headers=h)
        assert r.status_code == 403
        r2 = client.post(
            "/api/ai/predict-eta", headers=h,
            json={"device_type": "Телевизоры", "brand": "Samsung"},
        )
        assert r2.status_code == 403


def test_operator_sees_work_pages(client, operator_headers):
    # Оператор — всё, кроме аналитики: очередь call-центра и список ремонтов.
    r = client.get("/api/callcenter/queue", headers=operator_headers)
    assert r.status_code == 200
    r2 = client.get("/api/repairs", headers=operator_headers)
    assert r2.status_code == 200


def test_master_sees_only_own_repairs(client, master_headers, created_repair):
    # created_repair без мастера -> мастер не должен его видеть.
    own = client.get("/api/repairs", headers=master_headers)
    assert own.status_code == 200
    assert all(x["id"] != created_repair["id"] for x in own.json())

    get = client.get(f"/api/repairs/{created_repair['id']}", headers=master_headers)
    assert get.status_code == 403


def test_price_search_and_hint(client, admin_headers):
    r = client.get("/api/prices", headers=admin_headers, params={"type": "ТВ", "brand": "Samsung"})
    assert r.status_code == 200
    assert len(r.json()) >= 1

    r2 = client.get(
        "/api/prices/hint", headers=admin_headers, params={"type": "ТВ", "brand": "Samsung"}
    )
    hint = r2.json()["hint"]
    assert hint["price_min"] <= hint["price_max"]


def test_stats_overview_and_tiles(client, admin_headers):
    r = client.get("/api/stats/overview", headers=admin_headers)
    assert r.status_code == 200
    assert "total" in r.json()

    r2 = client.get("/api/stats/tiles", headers=admin_headers)
    assert r2.status_code == 200
    # At least the "Всего" tile exists.
    assert any(t["group"] == "Всего" for t in r2.json())


def test_ai_predict_eta_honest(client, admin_headers):
    r = client.post(
        "/api/ai/predict-eta",
        headers=admin_headers,
        json={"device_type": "ТВ", "brand": "Samsung"},
    )
    assert r.status_code == 200
    body = r.json()
    # Either a real estimate or honest "мало данных".
    assert body["eta_days"] is not None or body["message"] == "мало данных"

    r2 = client.post(
        "/api/ai/predict-eta",
        headers=admin_headers,
        json={"device_type": "НесуществующийТип"},
    )
    assert r2.json()["message"] == "мало данных"
