"""Админский CRUD всех полей: сотрудники, ремонты, клиенты, склад, прайс."""

import pytest


@pytest.fixture(autouse=True)
def _clear_web_session(client):
    """Сессионный TestClient общий: не оставляем cookie логина соседним тестам."""
    yield
    client.get("/logout", follow_redirects=False)
    client.cookies.clear()


def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return r.cookies


def test_admin_users_page_has_full_card_form(client):
    cookies = _login(client)
    page = client.get("/admin/users", cookies=cookies)
    assert page.status_code == 200
    assert 'action="/admin/users/create"' in page.text
    assert 'name="telegram"' in page.text
    assert 'name="extra_roles"' in page.text
    assert "Сохранить карточку" in page.text
    assert "/admin/users/" in page.text and "/update" in page.text


def test_admin_updates_employee_all_fields(client, admin_headers):
    cookies = _login(client)
    created = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Черновик",
            "email": "draft.emp@msb.local",
            "password": "draft123",
            "role": "operator",
        },
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]

    r = client.post(
        f"/admin/users/{uid}/update",
        cookies=cookies,
        data={
            "name": "Сердар Мастер",
            "email": "serdar.emp@msb.local",
            "phone": "+993 61 1112233",
            "telegram": "@serdar",
            "role": "master",
            "extra_roles": ["operator"],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    users = client.get("/api/admin/users", headers=admin_headers).json()
    emp = next(u for u in users if u["id"] == uid)
    assert emp["name"] == "Сердар Мастер"
    assert emp["email"] == "serdar.emp@msb.local"
    assert emp["phone"] == "+993 61 1112233"
    assert emp["telegram"] == "@serdar"
    assert emp["role"] == "master"
    assert "operator" in emp["roles"]

    gone = client.post(
        f"/admin/users/{uid}/delete",
        cookies=cookies,
        follow_redirects=False,
    )
    assert gone.status_code == 303, gone.text
    users = client.get("/api/admin/users", headers=admin_headers).json()
    emp = next(u for u in users if u["id"] == uid)
    assert emp["active"] is False


def test_master_cannot_edit_employees(client):
    cookies = _login(client, "master@msb.local", "master123")
    page = client.get("/admin/users", cookies=cookies, follow_redirects=False)
    assert page.status_code in (403, 303)


def test_admin_edits_and_deletes_repair_all_fields(client, city_id, admin_headers):
    cookies = _login(client)
    created = client.post(
        "/api/repairs",
        headers=admin_headers,
        json={
            "city_id": city_id,
            "client": {"full_name": "Старый Клиент", "phone": "+993611112233"},
            "device_type": "Телевизоры",
            "brand": "Samsung",
            "model": "UE43",
            "fault_client": "не включается",
        },
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    cid = created.json()["client_id"]

    page = client.get(f"/repairs/{rid}", cookies=cookies)
    assert page.status_code == 200
    assert 'action="/repairs/' in page.text and "/admin" in page.text
    assert "Админ: все поля карточки" in page.text
    assert "🗑 Удалить" in page.text

    r = client.post(
        f"/repairs/{rid}/admin",
        cookies=cookies,
        data={
            "client_name": "Новый Клиент",
            "client_phone": "+993619998877",
            "device_type": "Мониторы",
            "brand": "Dell",
            "model": "P2419H",
            "serial": "SN-ADMIN-1",
            "fault_client": "нет изображения",
            "fault_master": "матрица",
            "condition_notes": "царапина",
            "complectation": "Пульт, Кабель",
            "contact2_name": "Брат",
            "contact2_phone": "+99362000001",
            "contact2_relation": "родственник",
            "eta_days": "4",
            "is_delivery": "1",
            "delivery_district": "Парахат 7",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    repair = client.get(f"/api/repairs/{rid}", headers=admin_headers).json()
    assert repair["device_type"] == "Мониторы"
    assert repair["brand"] == "Dell"
    assert repair["model"] == "P2419H"
    assert repair["serial"] == "SN-ADMIN-1"
    assert repair["fault_client"] == "нет изображения"
    assert repair["fault_master"] == "матрица"
    assert repair["condition_notes"] == "царапина"
    assert repair["contact2_name"] == "Брат"
    assert repair["contact2_relation"] == "родственник"
    assert repair["is_delivery"] is True
    assert repair["delivery_district"] == "Парахат 7"
    assert repair["eta_days"] == 4
    assert repair["client_name"] == "Новый Клиент"
    assert "Пульт" in (repair.get("complectation") or {})

    client_card = client.get(f"/clients/{cid}", cookies=cookies)
    assert client_card.status_code == 200
    assert "Новый Клиент" in client_card.text

    gone = client.post(f"/repairs/{rid}/delete", cookies=cookies, follow_redirects=False)
    assert gone.status_code == 303, gone.text
    assert client.get(f"/api/repairs/{rid}", headers=admin_headers).status_code == 404


def test_master_cannot_admin_edit_or_delete_repair(client, city_id, admin_headers):
    created = client.post(
        "/api/repairs",
        headers=admin_headers,
        json={
            "city_id": city_id,
            "client": {"full_name": "Мастер Нет", "phone": "+993611000111"},
            "device_type": "Другое",
            "brand": "X",
        },
    )
    rid = created.json()["id"]
    cookies = _login(client, "master@msb.local", "master123")
    assert client.post(
        f"/repairs/{rid}/admin",
        cookies=cookies,
        data={"brand": "Hack"},
        follow_redirects=False,
    ).status_code == 403
    assert client.post(
        f"/repairs/{rid}/delete",
        cookies=cookies,
        follow_redirects=False,
    ).status_code == 403


def test_admin_edits_and_deletes_client(client, city_id, admin_headers):
    cookies = _login(client)
    created = client.post(
        "/api/repairs",
        headers=admin_headers,
        json={
            "city_id": city_id,
            "client": {"full_name": "Клиент Правка", "phone": "+993612223344"},
            "device_type": "Другое",
        },
    )
    cid = created.json()["client_id"]
    page = client.get(f"/clients/{cid}", cookies=cookies)
    assert page.status_code == 200
    assert f'action="/clients/{cid}/update"' in page.text

    r = client.post(
        f"/clients/{cid}/update",
        cookies=cookies,
        data={"full_name": "Клиент Новый", "phone": "+993612223355"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    page = client.get(f"/clients/{cid}", cookies=cookies)
    assert "Клиент Новый" in page.text

    gone = client.post(f"/clients/{cid}/delete", cookies=cookies, follow_redirects=False)
    assert gone.status_code == 303
    assert client.get(f"/clients/{cid}", cookies=cookies).status_code == 404


def test_admin_updates_part_equipment_and_price(client, admin_headers):
    cookies = _login(client)
    part = client.post(
        "/api/parts",
        headers=admin_headers,
        json={"name": "Конденсатор CRUD", "sku": "CRUD-CAP-1", "stock_qty": 5, "min_stock": 1},
    ).json()
    eq = client.post(
        "/api/equipment",
        headers=admin_headers,
        json={"name": "Донор CRUD", "brand": "LG", "status": "in_stock"},
    ).json()
    price = client.post(
        "/prices/create",
        cookies=cookies,
        data={"fault": "CRUD услуга", "price_avg": "150"},
        follow_redirects=False,
    )
    assert price.status_code == 303

    r = client.post(
        f"/parts/{part['id']}/update",
        cookies=cookies,
        data={
            "name": "Конденсатор 1000мкФ",
            "sku": "CRUD-CAP-1",
            "stock_qty": "12",
            "min_stock": "2",
            "sell_price": "40",
            "category": "Питание",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    saved = client.get("/api/parts", headers=admin_headers).json()
    row = next(p for p in saved if p["id"] == part["id"])
    assert row["name"] == "Конденсатор 1000мкФ"
    assert row["stock_qty"] == 12
    assert row["category"] == "Питание"

    r = client.post(
        f"/equipment/{eq['id']}/update",
        cookies=cookies,
        data={
            "name": "Донор OLED",
            "brand": "LG",
            "model": "C1",
            "status": "partial",
            "storage_place": "Полка 9",
            "components": "матрица, БП",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    eqs = client.get("/api/equipment", headers=admin_headers).json()
    erow = next(e for e in eqs if e["id"] == eq["id"])
    assert erow["name"] == "Донор OLED"
    assert erow["status"] == "partial"
    assert erow["storage_place"] == "Полка 9"

    page = client.get("/prices", cookies=cookies)
    assert "CRUD услуга" in page.text
    import re

    m = re.search(r'action="/prices/([0-9a-f-]{36})/update"', page.text)
    assert m, "форма правки прайса не найдена"
    pid = m.group(1)
    r = client.post(
        f"/prices/{pid}/update",
        cookies=cookies,
        data={"fault": "CRUD услуга правленная", "price_avg": "200", "typical_days": "3"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    page = client.get("/prices", cookies=cookies)
    assert "CRUD услуга правленная" in page.text

    assert client.post(
        f"/parts/{part['id']}/delete", cookies=cookies, follow_redirects=False
    ).status_code == 303
    assert client.post(
        f"/equipment/{eq['id']}/delete", cookies=cookies, follow_redirects=False
    ).status_code == 303


def test_master_cannot_edit_stock(client, admin_headers):
    part = client.post(
        "/api/parts",
        headers=admin_headers,
        json={"name": "Секретная деталь", "sku": "SEC-1", "stock_qty": 1},
    ).json()
    cookies = _login(client, "master@msb.local", "master123")
    assert client.post(
        f"/parts/{part['id']}/update",
        cookies=cookies,
        data={"name": "Взлом"},
        follow_redirects=False,
    ).status_code == 403
