"""Склад: купленная техника (CRUD + статусы) и ручные запчасти в ремонте."""


def test_equipment_crud(client, admin_headers):
    r = client.post(
        "/api/equipment",
        headers=admin_headers,
        json={
            "name": "Ноутбук",
            "brand": "Lenovo",
            "model": "ThinkPad T480",
            "purchase_price": 2500,
            "components": ["Матрица 14", "Блок питания", "Клавиатура"],
            "storage_place": "Склад, полка 3",
        },
    )
    assert r.status_code == 201, r.text
    eq = r.json()
    assert eq["status"] == "in_stock"
    assert eq["purchase_price"] == 2500
    assert eq["components"] == ["Матрица 14", "Блок питания", "Клавиатура"]
    assert eq["storage_place"] == "Склад, полка 3"
    assert eq["purchased_at"]

    # List
    r2 = client.get("/api/equipment", headers=admin_headers)
    assert r2.status_code == 200
    assert any(e["id"] == eq["id"] for e in r2.json())

    # Search by brand/model
    r3 = client.get(
        "/api/equipment", headers=admin_headers, params={"q": "thinkpad"}
    )
    assert r3.status_code == 200
    assert [e["id"] for e in r3.json()] == [eq["id"]]

    # Update
    r4 = client.patch(
        f"/api/equipment/{eq['id']}",
        headers=admin_headers,
        json={"model": "T480s", "purchase_price": 2600},
    )
    assert r4.status_code == 200
    assert r4.json()["model"] == "T480s"
    assert r4.json()["purchase_price"] == 2600


def test_equipment_status_actions(client, admin_headers):
    eq = client.post(
        "/api/equipment",
        headers=admin_headers,
        json={"name": "Моноблок", "brand": "HP", "purchase_price": 4000},
    ).json()

    r = client.post(
        f"/api/equipment/{eq['id']}/status",
        headers=admin_headers,
        json={"status": "partial"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "partial"

    r2 = client.post(
        f"/api/equipment/{eq['id']}/status",
        headers=admin_headers,
        json={"status": "dismantled"},
    )
    assert r2.json()["status"] == "dismantled"

    # Недопустимый статус -> 422
    r3 = client.post(
        f"/api/equipment/{eq['id']}/status",
        headers=admin_headers,
        json={"status": "bogus"},
    )
    assert r3.status_code == 422


def test_equipment_soft_delete(client, admin_headers):
    eq = client.post(
        "/api/equipment",
        headers=admin_headers,
        json={"name": "Холодильник", "brand": "Indesit"},
    ).json()

    r = client.delete(f"/api/equipment/{eq['id']}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # Из списка исчезла, по id — 404.
    remaining = client.get("/api/equipment", headers=admin_headers).json()
    assert all(e["id"] != eq["id"] for e in remaining)
    assert client.get(f"/api/equipment/{eq['id']}", headers=admin_headers).status_code == 404


def test_equipment_aware_datetime_normalized(client, admin_headers):
    # Aware-datetime (с таймзоной) — такое фронт присылал через toISOString.
    # Бэкенд обязан нормализовать до naive UTC: иначе asyncpg падает с
    # DataError на naive TIMESTAMP-колонке (can't subtract offset-naive...).
    r = client.post(
        "/api/equipment",
        headers=admin_headers,
        json={
            "name": "Монитор",
            "brand": "Dell",
            "purchased_at": "2026-09-04T07:00:00+05:00",
        },
    )
    assert r.status_code == 201, r.text
    eq = r.json()
    # 07:00+05:00 == 02:00 UTC, хранится без таймзоны.
    assert eq["purchased_at"] == "2026-09-04T02:00:00"
    assert "Z" not in eq["purchased_at"] and "+" not in eq["purchased_at"]

    r2 = client.patch(
        f"/api/equipment/{eq['id']}",
        headers=admin_headers,
        json={"purchased_at": "2026-09-01T05:30:00Z"},
    )
    assert r2.status_code == 200
    assert r2.json()["purchased_at"] == "2026-09-01T05:30:00"


def test_operator_cannot_manage_equipment(client, admin_headers, operator_headers):
    eq = client.post(
        "/api/equipment",
        headers=admin_headers,
        json={"name": "Телевизор", "brand": "Samsung"},
    ).json()

    # Чтение — можно, изменение — нет.
    assert client.get("/api/equipment", headers=operator_headers).status_code == 200
    assert (
        client.post(
            "/api/equipment", headers=operator_headers, json={"name": "Запрещено"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/equipment/{eq['id']}", headers=operator_headers, json={"name": "x"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/equipment/{eq['id']}/status",
            headers=operator_headers,
            json={"status": "dismantled"},
        ).status_code
        == 403
    )


# --- Ручные запчасти в карточке ремонта (название + цена, без склада) ---

def test_manual_part_add_and_remove(client, admin_headers, created_repair):
    r = client.post(
        f"/api/repairs/{created_repair['id']}/parts",
        headers=admin_headers,
        json={"name": "Матрица 15.6 FHD", "price": 900, "qty": 1},
    )
    assert r.status_code == 201, r.text
    rp = r.json()
    assert rp["part_name"] == "Матрица 15.6 FHD"
    assert rp["price"] == 900
    assert rp["is_manual"] is True

    # Позиция появилась в каталоге со нулевым остатком.
    parts = client.get(
        "/api/parts", headers=admin_headers, params={"q": "Матрица 15.6 FHD"}
    ).json()
    assert len(parts) == 1
    assert parts[0]["stock_qty"] == 0
    assert parts[0]["sell_price"] == 900

    # Удаление НЕ возвращает «остаток» (его не было).
    r2 = client.delete(
        f"/api/repairs/{created_repair['id']}/parts/{rp['id']}", headers=admin_headers
    )
    assert r2.status_code == 200
    parts2 = client.get(
        "/api/parts", headers=admin_headers, params={"q": "Матрица 15.6 FHD"}
    ).json()
    assert parts2[0]["stock_qty"] == 0


def test_manual_part_links_existing_catalog_entry(client, admin_headers, created_repair):
    parts = client.get("/api/parts", headers=admin_headers).json()
    existing = next(p for p in parts if p["name"] == "Тестовая деталь")

    # То же название (вдруг с другим регистром) — привязываем к существующей.
    r = client.post(
        f"/api/repairs/{created_repair['id']}/parts",
        headers=admin_headers,
        json={"name": "тестовая деталь", "price": 500},
    )
    assert r.status_code == 201, r.text
    assert r.json()["part_id"] == existing["id"]
    assert r.json()["is_manual"] is True
    assert r.json()["price"] == 500


def test_repair_part_requires_source(client, admin_headers, created_repair):
    r = client.post(
        f"/api/repairs/{created_repair['id']}/parts",
        headers=admin_headers,
        json={"qty": 1},
    )
    assert r.status_code == 422
