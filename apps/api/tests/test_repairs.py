def test_create_repair_number(client, created_repair):
    assert created_repair["number"].startswith("TV-ASG-2026-")
    assert created_repair["status"] == "Принято"
    assert created_repair["storage_until"] is not None


def test_idempotency(client, operator_headers, city_id):
    payload = {
        "city_id": city_id,
        "client": {"full_name": "Идемпотент", "phone": "+79991112233"},
        "device_type": "ТВ",
    }
    r1 = client.post(
        "/api/repairs", headers={**operator_headers, "Idempotency-Key": "idem-1"}, json=payload
    )
    r2 = client.post(
        "/api/repairs", headers={**operator_headers, "Idempotency-Key": "idem-1"}, json=payload
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


def test_public_page(client, created_repair):
    token = created_repair["public_token"]
    r = client.get(f"/api/public/r/{token}")
    assert r.status_code == 200
    body = r.json()
    # Limited DTO: no internal fields.
    assert "fault_master" not in body
    assert "client_phone" not in body
    assert body["storage_text"]


def test_public_page_not_found(client):
    r = client.get("/api/public/r/does-not-exist")
    assert r.status_code == 404


def test_master_scoped_to_own(client, master_headers, created_repair):
    r = client.get("/api/repairs", headers=master_headers)
    assert r.status_code == 200
    numbers = {x["number"] for x in r.json()["items"]}
    # The operator-created repair has no master assigned, so master shouldn't see it.
    assert created_repair["number"] not in numbers


def test_master_intake_not_self_assigned(client, master_headers, city_id):
    """Мастер НЕ назначает себя на приёмке: «Мастер»/«Помощники» остаются
    пустыми, назначение — только администратор или оператор."""
    r = client.post(
        "/api/repairs",
        headers={**master_headers, "Idempotency-Key": "master-intake-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "От Мастера", "phone": "+993 61 999999"},
            "device_type": "ТВ",
        },
    )
    assert r.status_code == 201
    assert r.json()["master_id"] is None
    assert r.json()["master_names"] == []
    assert r.json()["status"] == "Принято"

    # Мастер не может назначить себя (или другого) через PATCH — 403.
    me = client.get("/api/auth/me", headers=master_headers).json()
    r2 = client.patch(
        f"/api/repairs/{r.json()['id']}",
        headers=master_headers,
        json={"master_ids": [me["id"]]},
    )
    assert r2.status_code == 403
    r3 = client.patch(
        f"/api/repairs/{r.json()['id']}",
        headers=master_headers,
        json={"helper_ids": [me["id"]]},
    )
    assert r3.status_code == 403


def test_repair_without_master_stays_new(client, operator_headers, city_id):
    """Без мастера при приёмке ремонт остаётся в «Принято», как раньше."""
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "no-master-intake-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Без мастера", "phone": "+993 61 888888"},
            "device_type": "ТВ",
        },
    )
    assert r.status_code == 201
    assert r.json()["master_id"] is None
    assert r.json()["status"] == "Принято"


def test_repair_created_with_master_by_operator_is_diag(
    client, admin_headers, operator_headers, city_id
):
    """Оператор при приёмке сразу указал мастера — статус тоже «Диагностика»."""
    users = client.get("/api/admin/users", headers=admin_headers).json()
    master = next(u for u in users if u["email"] == "master@msb.local")
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "operator-intake-master-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "С мастером сразу", "phone": "+993 61 777333"},
            "device_type": "ТВ",
            "master_id": master["id"],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "Диагностика"


def test_is_delivery_flag_default_and_set_on_intake(client, operator_headers, city_id):
    """Чекбокс «Заказ с доставкой» на приёмке — по умолчанию выключен, можно включить."""
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "delivery-default-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Без доставки", "phone": "+993 61 444555"},
            "device_type": "ТВ",
        },
    )
    assert r.status_code == 201
    assert r.json()["is_delivery"] is False

    r2 = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "delivery-set-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "С доставкой", "phone": "+993 61 444556"},
            "device_type": "ТВ",
            "is_delivery": True,
        },
    )
    assert r2.status_code == 201
    assert r2.json()["is_delivery"] is True


def test_is_delivery_flag_editable_via_patch(client, operator_headers, city_id):
    """Флаг доставки можно включить/выключить на карточке ремонта после приёмки."""
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "delivery-patch-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Доставка потом", "phone": "+993 61 444557"},
            "device_type": "ТВ",
        },
    )
    repair = r.json()
    assert repair["is_delivery"] is False

    r2 = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"is_delivery": True},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["is_delivery"] is True

    r3 = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"is_delivery": False},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["is_delivery"] is False


def test_consent_repair_recorded(client, operator_headers, city_id):
    """Согласие на ремонт фиксируется в договоре (consent_repair_at)."""
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "consent-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Согласный", "phone": "+993 61 777777"},
            "device_type": "ТВ",
            "consent_repair": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["consent_repair_at"] is not None

    r2 = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "consent-2"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Без согласия", "phone": "+993 61 888888"},
            "device_type": "ТВ",
        },
    )
    assert r2.json()["consent_repair_at"] is None


def test_finalize_repair(client, admin_headers, created_repair):
    """Оператор оформляет починку: расходы + цена + оплата."""
    r = client.patch(
        f"/api/repairs/{created_repair['id']}",
        headers=admin_headers,
        json={"cost_amount": 300, "price_final": 550, "paid": True, "status": "Выдано"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cost_amount"] == 300
    assert body["price_final"] == 550
    assert body["paid"] is True
    assert body["status"] == "Выдано"


def test_update_status_timeline(client, admin_headers, created_repair):
    r = client.patch(
        f"/api/repairs/{created_repair['id']}",
        headers=admin_headers,
        json={"status": "Диагностика"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "Диагностика"
    types = [e["type"] for e in r.json()["events"]]
    assert "status_change" in types


def test_master_board_only_assigned(
    client, admin_headers, operator_headers, city_id
):
    """Мастер на странице «Все ремонты» видит ТОЛЬКО ремонты, назначенные ему."""
    # Два мастера.
    m1 = client.post(
        "/api/admin/users", headers=admin_headers,
        json={"name": "Мастер У", "email": "mu@msb.local",
              "password": "pass123", "role": "master"},
    ).json()
    m2 = client.post(
        "/api/admin/users", headers=admin_headers,
        json={"name": "Мастер Д", "email": "md@msb.local",
              "password": "pass123", "role": "master"},
    ).json()
    h1 = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "mu@msb.local", "password": "pass123"}
    ).json()["access_token"]}
    h2 = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "md@msb.local", "password": "pass123"}
    ).json()["access_token"]}

    def mk(i):
        return client.post(
            "/api/repairs",
            headers={**operator_headers, "Idempotency-Key": f"master-board-{i}"},
            json={
                "city_id": city_id,
                "client": {"full_name": f"Клиент {i}",
                           "phone": f"+79970{i:06d}0", "consent_pdn": True},
                "device_type": "Телевизоры",
                "brand": "Samsung",
            },
        ).json()

    # 3 ремонта: первые 2 назначены МастерУ, третий — Мастеру Д.
    r1 = mk(1); client.patch(f"/api/repairs/{r1['id']}", headers=operator_headers,
                             json={"master_ids": [m1["id"]]})
    r2 = mk(2); client.patch(f"/api/repairs/{r2['id']}", headers=operator_headers,
                             json={"master_ids": [m1["id"]]})
    r3 = mk(3); client.patch(f"/api/repairs/{r3['id']}", headers=operator_headers,
                             json={"master_ids": [m2["id"]]})

    ids1 = {x["id"] for x in client.get(
        "/api/repairs", headers=h1, params={"stage": "all", "page_size": 50}
    ).json()["items"]}
    assert ids1 == {r1["id"], r2["id"]}, f"Мастер У видит лишнее: {ids1}"

    ids2 = {x["id"] for x in client.get(
        "/api/repairs", headers=h2, params={"stage": "all", "page_size": 50}
    ).json()["items"]}
    assert ids2 == {r3["id"]}, f"Мастер Д видит лишнее: {ids2}"

    # Счётчики по этапам у мастера тоже только по его ремонтам.
    sc1 = client.get("/api/repairs/stage-counts", headers=h1).json()
    assert sc1["all"] == 2
    sc2 = client.get("/api/repairs/stage-counts", headers=h2).json()
    assert sc2["all"] == 1

    # Чужой ремонт открыть напрямую мастер не может.
    assert client.get(f"/api/repairs/{r3['id']}", headers=h1).status_code == 403
    assert client.get(f"/api/repairs/{r1['id']}", headers=h2).status_code == 403
