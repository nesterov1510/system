"""Видимость ремонтов для мастера во вкладке «Все ремонты».

Мастер видит только:
* свои ремонты — назначенные напрямую или через список исполнителей;
* свободные — без исполнителя, чтобы взять заказ себе.

Чужие ремонты с назначенным исполнителем не показываются ни в таблице, ни на
доске, ни в счётчиках этапов, и карточка такого ремонта не открывается.
Старшие роли (администратор, оператор) видят всё.
"""
import re

import pytest


def _intake(client, headers, city_id, key, phone="+993 61 500000", master_id=None):
    """Приёмка через API (как в остальных тестах приёмки)."""
    body = {
        "city_id": city_id,
        "client": {"full_name": "Клиент Видимости", "phone": phone, "consent_pdn": True},
        "device_type": "Телевизоры",
        "brand": "LG",
        "model": "32LK6100",
        "fault_client": "нет изображения",
    }
    if master_id is not None:
        body["master_id"] = master_id
    return client.post(
        "/api/repairs", headers={**headers, "Idempotency-Key": key}, json=body
    )


@pytest.fixture(scope="session")
def two_masters(client, admin_headers):
    out = {}
    for key, name, email in (
        ("vis-m1", "Мастер Первый", "vis-m1@msb.local"),
        ("vis-m2", "Мастер Второй", "vis-m2@msb.local"),
    ):
        r = client.post(
            "/api/admin/users", headers=admin_headers,
            json={"name": name, "email": email, "password": "pass123", "role": "master"},
        )
        assert r.status_code == 201, r.text
        out[key] = r.json()
    return out


def _login(client, email):
    r = client.post(
        "/login",
        data={"email": email, "password": "pass123", "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "/login" not in r.headers["location"]
    return dict(r.cookies)


def _assign(client, operator_headers, repair_id, master_id):
    r = client.patch(
        f"/api/repairs/{repair_id}", headers=operator_headers,
        json={"master_ids": [master_id]},
    )
    assert r.status_code == 200, r.text


def _table_ids(client, cookies):
    """id ремонтов, показанных на странице «Все ремонты».

    Номера в таблице нет (колонки: дата, техника, неисправность…), поэтому
    проверяем по ссылкам на карточки.
    """
    r = client.get("/repairs", cookies=cookies)
    assert r.status_code == 200
    return set(re.findall(r"/repairs/([0-9a-f-]{36})", r.text))


def test_master_table_shows_own_and_unassigned(
    client, operator_headers, two_masters, city_id
):
    mine = _intake(client, operator_headers, city_id, "vis-1", phone="+993 61 500001")
    assert mine.status_code == 201
    foreign = _intake(client, operator_headers, city_id, "vis-2", phone="+993 61 500002")
    assert foreign.status_code == 201
    free = _intake(client, operator_headers, city_id, "vis-3", phone="+993 61 500003")
    assert free.status_code == 201

    _assign(client, operator_headers, mine.json()["id"], two_masters["vis-m1"]["id"])
    _assign(client, operator_headers, foreign.json()["id"], two_masters["vis-m2"]["id"])

    cookies = _login(client, "vis-m1@msb.local")
    shown = _table_ids(client, cookies)

    assert mine.json()["id"] in shown, "свой ремонт не показан"
    assert free.json()["id"] in shown, "свободный ремонт не показан"
    assert foreign.json()["id"] not in shown, "показан чужой назначенный ремонт"


def test_master_board_shows_own_and_unassigned(
    client, operator_headers, two_masters, city_id
):
    mine = _intake(client, operator_headers, city_id, "vis-4", phone="+993 61 500004")
    foreign = _intake(client, operator_headers, city_id, "vis-5", phone="+993 61 500005")
    free = _intake(client, operator_headers, city_id, "vis-6", phone="+993 61 500006")
    _assign(client, operator_headers, mine.json()["id"], two_masters["vis-m1"]["id"])
    _assign(client, operator_headers, foreign.json()["id"], two_masters["vis-m2"]["id"])

    cookies = _login(client, "vis-m1@msb.local")
    r = client.get("/repairs?view=board", cookies=cookies)
    assert r.status_code == 200
    shown = set(re.findall(r"/repairs/([0-9a-f-]{36})", r.text))
    assert mine.json()["id"] in shown
    assert free.json()["id"] in shown
    assert foreign.json()["id"] not in shown


def test_master_can_open_unassigned_and_take_it(
    client, operator_headers, two_masters, city_id
):
    free = _intake(client, operator_headers, city_id, "vis-7", phone="+993 61 500007")
    rid = free.json()["id"]
    cookies = _login(client, "vis-m1@msb.local")

    assert client.get(f"/repairs/{rid}", cookies=cookies).status_code == 200

    r = client.post(
        f"/repairs/{rid}/master-action",
        data={"action": "master", "user_id": two_masters["vis-m1"]["id"], "next": "/repairs"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[:200])

    # ремонт стал своим — остаётся в списке первого мастера
    assert rid in _table_ids(client, cookies)

    # ремонт занят — значит из списка второго мастера он пропадает
    cookies2 = _login(client, "vis-m2@msb.local")
    assert rid not in _table_ids(client, cookies2)


def test_master_cannot_open_foreign_assigned_card(
    client, operator_headers, two_masters, city_id
):
    foreign = _intake(client, operator_headers, city_id, "vis-8", phone="+993 61 500008")
    _assign(client, operator_headers, foreign.json()["id"], two_masters["vis-m2"]["id"])

    cookies = _login(client, "vis-m1@msb.local")
    assert client.get(f"/repairs/{foreign.json()['id']}", cookies=cookies).status_code == 403


def test_helper_also_sees_the_repair(client, operator_headers, two_masters, city_id):
    """Назначенный помощником мастер видит ремонт как свой."""
    repair = _intake(client, operator_headers, city_id, "vis-9", phone="+993 61 500009")
    r = client.patch(
        f"/api/repairs/{repair.json()['id']}", headers=operator_headers,
        json={"helper_ids": [two_masters["vis-m1"]["id"]]},
    )
    assert r.status_code == 200, r.text

    cookies = _login(client, "vis-m1@msb.local")
    assert repair.json()["id"] in _table_ids(client, cookies)


def test_senior_roles_still_see_everything(
    client, operator_headers, admin_headers, two_masters, city_id
):
    a = _intake(client, operator_headers, city_id, "vis-10", phone="+993 61 500010")
    b = _intake(client, operator_headers, city_id, "vis-11", phone="+993 61 500011")
    _assign(client, operator_headers, a.json()["id"], two_masters["vis-m1"]["id"])
    _assign(client, operator_headers, b.json()["id"], two_masters["vis-m2"]["id"])

    ids = {x["id"] for x in client.get(
        "/api/repairs", headers=operator_headers, params={"stage": "all", "page_size": 100}
    ).json()["items"]}
    assert {a.json()["id"], b.json()["id"]} <= ids

    admin_ids = {x["id"] for x in client.get(
        "/api/repairs", headers=admin_headers, params={"stage": "all", "page_size": 100}
    ).json()["items"]}
    assert {a.json()["id"], b.json()["id"]} <= admin_ids


def test_master_search_does_not_leak_foreign_repairs(
    client, operator_headers, two_masters, city_id
):
    """Поиск тоже ограничен: по номеру чужой ремонт не находится."""
    foreign = _intake(client, operator_headers, city_id, "vis-12", phone="+993 61 500012")
    _assign(client, operator_headers, foreign.json()["id"], two_masters["vis-m2"]["id"])

    r = client.get(
        "/api/repairs",
        headers={
            "Authorization": "Bearer " + client.post(
                "/api/auth/login",
                json={"email": "vis-m1@msb.local", "password": "pass123"},
            ).json()["access_token"]
        },
        params={"q": foreign.json()["number"], "stage": "all", "page_size": 50},
    )
    assert r.status_code == 200
    assert foreign.json()["id"] not in {x["id"] for x in r.json()["items"]}


def _bearer(client, email):
    token = client.post(
        "/api/auth/login", json={"email": email, "password": "pass123"}
    ).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def _api_ids(client, headers):
    return {
        x["id"] for x in client.get(
            "/api/repairs", headers=headers, params={"stage": "all", "page_size": 100}
        ).json()["items"]
    }


def test_own_intake_without_executor_is_not_free_for_others(
    client, operator_headers, two_masters, city_id
):
    """Приёмка, которую мастер принял на себя, занята им — не «свободная».

    Исполнитель при этом не назначен, поэтому раньше ремонт уходил в общую
    очередь и второй мастер видел чужую работу.
    """
    m1 = _bearer(client, "vis-m1@msb.local")
    r = _intake(client, m1, city_id, "vis-13", phone="+993 61 500013")
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["master_id"] is None, "исполнитель не назначен"

    # Принимающий видит свой ремонт.
    assert rid in _table_ids(client, _login(client, "vis-m1@msb.local"))
    # Второй мастер — нет: приёмка чужая.
    assert rid not in _table_ids(client, _login(client, "vis-m2@msb.local"))
    assert rid not in _api_ids(client, _bearer(client, "vis-m2@msb.local"))
    # Старшая роль видит всё.
    assert rid in _api_ids(client, operator_headers)


def test_finished_unassigned_repair_is_not_in_master_list(
    client, operator_headers, two_masters, city_id
):
    """Завершённый ремонт без исполнителя брать нечего — он не в очереди."""
    r = _intake(client, operator_headers, city_id, "vis-14", phone="+993 61 500014")
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    done = client.patch(
        f"/api/repairs/{rid}", headers=operator_headers, json={"status": "Завершён"}
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "Завершён"

    for email in ("vis-m1@msb.local", "vis-m2@msb.local"):
        assert rid not in _table_ids(client, _login(client, email))
        assert rid not in _api_ids(client, _bearer(client, email))
    assert rid in _api_ids(client, operator_headers)
