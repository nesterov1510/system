def test_create_repair_number(client, created_repair):
    assert created_repair["number"].startswith("TV-ASG-2026-")
    assert created_repair["status"] == "Новый"
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


def test_master_sees_full_repair_list(client, master_headers, created_repair):
    """Список ремонтов у мастера общий: в нём видно и свободные заказы."""
    # page_size ограничен сотней, а ремонтов в тестовой БД со временем
    # становится больше — поэтому листаем до конца.
    numbers, page = set(), 1
    while True:
        r = client.get(
            "/api/repairs", headers=master_headers,
            params={"page_size": 100, "page": page},
        )
        assert r.status_code == 200
        data = r.json()
        numbers.update(x["number"] for x in data["items"])
        if page * 100 >= data["total"]:
            break
        page += 1
    assert created_repair["number"] in numbers


def test_master_intake_not_self_assigned(
    client, admin_headers, master_headers, city_id
):
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
    assert r.json()["status"] == "Новый"

    # Свободный ремонт мастер берёт себе сам — статус уходит в диагностику.
    me = client.get("/api/auth/me", headers=master_headers).json()
    r2 = client.patch(
        f"/api/repairs/{r.json()['id']}",
        headers=master_headers,
        json={"master_ids": [me["id"]]},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["master_id"] == me["id"]
    assert r2.json()["status"] == "На диагностике"

    # Помощника к своему ремонту он добавить может (другого сотрудника).
    helper = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"name": "Помощник П", "email": "helper-p@msb.local",
              "password": "pass123", "role": "master"},
    )
    assert helper.status_code == 201, helper.text
    r3 = client.patch(
        f"/api/repairs/{r.json()['id']}",
        headers=master_headers,
        json={"helper_ids": [helper.json()["id"]]},
    )
    assert r3.status_code == 200, r3.text
    assert helper.json()["id"] in r3.json()["helper_ids"]

    # Себя помощником к своему же ремонту не добавить — он уже мастер.
    r4 = client.patch(
        f"/api/repairs/{r.json()['id']}",
        headers=master_headers,
        json={"helper_ids": [me["id"]]},
    )
    assert r4.status_code == 200, r4.text
    assert me["id"] not in r4.json()["helper_ids"]


def test_repair_without_master_stays_new(client, operator_headers, city_id):
    """Без мастера при приёмке ремонт остаётся в «Новый», как раньше."""
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
    assert r.json()["status"] == "Новый"


def test_repair_created_with_master_by_operator_is_diag(
    client, admin_headers, operator_headers, city_id
):
    """Оператор при приёмке сразу указал мастера — статус «На диагностике»."""
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
    assert r.json()["status"] == "На диагностике"


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
        json={"cost_amount": 300, "price_final": 550, "paid": True, "status": "Завершён"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cost_amount"] == 300
    assert body["price_final"] == 550
    assert body["paid"] is True
    assert body["status"] == "Завершён"
    # Готовность фиксируется датой, а не отдельным статусом.
    assert body["ready_at"]


def test_update_status_timeline(client, admin_headers, created_repair):
    r = client.patch(
        f"/api/repairs/{created_repair['id']}",
        headers=admin_headers,
        json={"status": "На диагностике"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "На диагностике"
    types = [e["type"] for e in r.json()["events"]]
    assert "status_change" in types


def test_master_sees_own_and_unassigned_only(
    client, admin_headers, operator_headers, city_id
):
    """В «Все ремонты» мастер видит свои ремонты и свободные — чужие нет."""
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

    # Счётчики измеряем дельтой: база в тестах общая для всей сессии.
    sc1_before = client.get("/api/repairs/stage-counts", headers=h1).json()
    sc2_before = client.get("/api/repairs/stage-counts", headers=h2).json()

    # 4 ремонта: r1 и r2 — у Мастера У, r3 — у Мастера Д, r4 свободен.
    r1 = mk(1); client.patch(f"/api/repairs/{r1['id']}", headers=operator_headers,
                             json={"master_ids": [m1["id"]]})
    r2 = mk(2); client.patch(f"/api/repairs/{r2['id']}", headers=operator_headers,
                             json={"master_ids": [m1["id"]]})
    r3 = mk(3); client.patch(f"/api/repairs/{r3['id']}", headers=operator_headers,
                             json={"master_ids": [m2["id"]]})
    r4 = mk(4)  # исполнитель не назначен — его может взять любой мастер

    ids1 = {x["id"] for x in client.get(
        "/api/repairs", headers=h1, params={"stage": "all", "page_size": 50}
    ).json()["items"]}
    assert {r1["id"], r2["id"]} <= ids1, f"Мастер У не видит своих: {ids1}"
    assert r4["id"] in ids1, "свободный ремонт не виден мастеру"
    assert r3["id"] not in ids1, "чужой назначенный ремонт виден мастеру"

    ids2 = {x["id"] for x in client.get(
        "/api/repairs", headers=h2, params={"stage": "all", "page_size": 50}
    ).json()["items"]}
    assert r3["id"] in ids2, f"Мастер Д не видит своего: {ids2}"
    assert r4["id"] in ids2, "свободный ремонт не виден мастеру"
    assert r1["id"] not in ids2 and r2["id"] not in ids2, "чужие ремонты видны"

    # Счётчики этапов совпадают со списком: свои + свободные.
    # Мастеру У добавились r1, r2 (свои) и r4 (свободный) — 3.
    # Мастеру Д — r3 (свой) и r4 (свободный) — 2.
    sc1 = client.get("/api/repairs/stage-counts", headers=h1).json()
    assert sc1["all"] - sc1_before["all"] == 3, (sc1_before, sc1)
    sc2 = client.get("/api/repairs/stage-counts", headers=h2).json()
    assert sc2["all"] - sc2_before["all"] == 2, (sc2_before, sc2)

    # Свободный ремонт мастер открывает и забирает себе.
    assert client.get(f"/api/repairs/{r4['id']}", headers=h1).status_code == 200
    # Чужой назначенный — не открывается и не правится.
    assert client.get(f"/api/repairs/{r3['id']}", headers=h1).status_code == 403
    assert client.patch(
        f"/api/repairs/{r3['id']}", headers=h1, json={"master_ids": [m1["id"]]}
    ).status_code == 403


def test_search_by_number_and_serial(client, operator_headers, city_id):
    """Номер и серийник напечатаны на этикетке — по ним карточка обязана находиться."""
    created = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "search-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Поиск Клиент", "phone": "+993 61 880099", "consent_pdn": True},
            "device_type": "Телевизоры",
            "brand": "Sony",
            "serial": "SN-SEARCH-77",
            "fault_client": "не включается",
        },
    )
    assert created.status_code == 201, created.text
    number = created.json()["number"]

    for query in (number, number.split("-", 1)[1], "sn-search-77"):
        r = client.get("/api/repairs", headers=operator_headers, params={"q": query})
        assert r.status_code == 200, r.text
        numbers = [x["number"] for x in r.json()["items"]]
        assert number in numbers, f"поиск {query!r} не нашёл ремонт: {numbers}"
