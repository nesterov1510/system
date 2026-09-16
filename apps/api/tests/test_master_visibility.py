"""Видимость ремонтов для мастера во вкладке «Все ремонты».

Мастер видит только:
* свои ремонты — назначенные напрямую или через список исполнителей;
* свободные — без исполнителя, чтобы взять заказ себе.

Чужие ремонты с назначенным исполнителем не показываются ни в таблице, ни на
доске, ни в счётчиках этапов, и карточка такого ремонта не открывается.
Старшие роли (администратор, оператор) видят всё.
"""
import re
import uuid

import pytest


def _intake(client, headers, city_id, key, phone="+993 61 500000", master_id=None,
            name="Клиент Видимости"):
    """Приёмка через API (как в остальных тестах приёмки)."""
    body = {
        "city_id": city_id,
        "client": {"full_name": name, "phone": phone, "consent_pdn": True},
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


def _login(client, email, password="pass123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
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


def test_master_cannot_take_another_masters_intake(
    client, operator_headers, two_masters, city_id
):
    """Чужую приёмку без исполнителя второй мастер себе не переписывает.

    Ремонта нет в его списке, и прямое действие «Взять себе» тоже закрыто:
    приёмку оформил другой мастер, заказ уже занят им.
    """
    m1 = _bearer(client, "vis-m1@msb.local")
    r = _intake(client, m1, city_id, "vis-15", phone="+993 61 500015")
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    cookies2 = _login(client, "vis-m2@msb.local")

    action = client.post(
        f"/repairs/{rid}/master-action",
        data={
            "action": "master",
            "user_id": two_masters["vis-m2"]["id"],
            "next": "/repairs",
        },
        cookies=cookies2,
        follow_redirects=False,
    )
    assert action.status_code == 403, (action.status_code, action.text[:200])

    # исполнитель не сменился — приёмка осталась у того, кто её оформил
    current = client.get(f"/api/repairs/{rid}", headers=operator_headers).json()
    assert current["master_id"] is None, current["master_id"]

    # сам приёмщик по-прежнему может назначить себя исполнителем
    own_action = client.post(
        f"/repairs/{rid}/master-action",
        data={
            "action": "master",
            "user_id": two_masters["vis-m1"]["id"],
            "next": "/repairs",
        },
        cookies=_login(client, "vis-m1@msb.local"),
        follow_redirects=False,
    )
    assert own_action.status_code == 303, (own_action.status_code, own_action.text[:200])
    after = client.get(f"/api/repairs/{rid}", headers=operator_headers).json()
    assert after["master_id"] == two_masters["vis-m1"]["id"], after["master_id"]


def test_free_check_fails_closed_without_loaded_acceptor():
    """Без подгруженного приёмщика ремонт не считается свободным.

    Роль приёмщика живёт в связанном пользователе. Если связь не загружена,
    принадлежность определить нельзя — правило обязано закрыть доступ, а не
    открыть чужой заказ. Во всех боевых путях связь подгружена
    (`selectinload` в `_get_repair_or_404` и `_load_repair`), поэтому свободные
    ремонты из общей очереди остаются доступны (проверено HTTP-тестами выше).
    """
    from app.core.permissions import (
        can_assign_repair_masters,
        can_view_repair,
        is_free_repair,
    )
    from app.db.models import Repair, User

    # id задаём явно: у неприсоединённого к сессии объекта первичный ключ ещё
    # None, и сравнение accepted_by == user.id совпало бы как None == None.
    acceptor = User(id=uuid.uuid4(), name="Мастер", email="u@msb.local",
                    role="master", extra_permissions=[])
    other = User(id=uuid.uuid4(), name="Другой", email="o@msb.local",
                 role="master", extra_permissions=[])
    repair = Repair(
        id=uuid.uuid4(), client_id=uuid.uuid4(), device_type="Телевизоры",
        brand="LG", model="43", fault_client="нет звука", status="Новый",
        accepted_by=acceptor.id,
    )
    repair.masters = []
    assert acceptor.id != other.id

    assert is_free_repair(repair) is False
    assert can_view_repair(other, repair) is False
    assert can_assign_repair_masters(other, repair) is False


def test_intake_handed_to_another_master_is_not_own_anymore(
    client, operator_headers, two_masters, city_id
):
    """Приёмка, переданная другому мастеру, у приёмщика больше не «своя».

    Мастер А оформил приёмку, администратор назначил исполнителем мастера Б,
    ремонт завершили и не оплатили. Раньше `own()` считал ремонт своим по
    `accepted_by` безусловно — и приёмщик видел завершённый неоплаченный
    заказ другого мастера.
    """
    m1 = _bearer(client, "vis-m1@msb.local")
    r = _intake(client, m1, city_id, "vis-16", phone="+993 61 500016")
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["master_id"] is None

    _assign(client, operator_headers, rid, two_masters["vis-m2"]["id"])
    done = client.patch(
        f"/api/repairs/{rid}", headers=operator_headers, json={"status": "Завершён"}
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "Завершён"
    assert done.json()["paid"] is False

    # исполнитель видит свой заказ
    assert rid in _table_ids(client, _login(client, "vis-m2@msb.local"))
    # приёмщик — уже нет: заказ передан другому мастеру
    assert rid not in _table_ids(client, _login(client, "vis-m1@msb.local"))
    assert rid not in _api_ids(client, m1)
    assert client.get(
        f"/repairs/{rid}", cookies=_login(client, "vis-m1@msb.local")
    ).status_code == 403


def test_master_cannot_open_callcenter_queue(client, two_masters):
    """Очередь колл-центра мастеру недоступна ни в API, ни на веб-странице.

    Веб-страница `/callcenter` звала `_queue()` напрямую, минуя проверку прав,
    которая есть у `/api/callcenter/queue`, — и отдавала мастеру все ремонты
    сервиса в обход области видимости «Все ремонты».
    """
    cookies = _login(client, "vis-m1@msb.local")
    assert client.get("/callcenter", cookies=cookies).status_code == 403

    api = client.get("/api/callcenter/queue", headers=_bearer(client, "vis-m1@msb.local"))
    assert api.status_code == 403, api.text[:200]


def test_master_client_list_is_scoped(client, operator_headers, two_masters, city_id):
    """Список клиентов мастеру — только те, у кого есть доступные ему ремонты.

    Эндпоинт `/api/repairs/clients/list` отдавал мастеру всю базу клиентов
    сервиса с телефонами и счётчиками чужих ремонтов, хотя страница `/clients`
    была ограничена. Границы должны совпадать со списком «Все ремонты».
    """
    foreign = _intake(client, operator_headers, city_id, "vis-17", phone="+993 61 500017")
    assert foreign.status_code == 201, foreign.status_code
    _assign(client, operator_headers, foreign.json()["id"], two_masters["vis-m2"]["id"])
    foreign_client = foreign.json()["client_id"]

    m1 = _bearer(client, "vis-m1@msb.local")
    listed = {x["id"] for x in client.get("/api/repairs/clients/list", headers=m1).json()}
    assert foreign_client not in listed, "чужой клиент виден в списке"

    # счётчик ремонтов у видимого клиента считает только доступные мастеру
    own = _intake(client, operator_headers, city_id, "vis-18", phone="+993 61 500018")
    assert own.status_code == 201, own.text
    _assign(client, operator_headers, own.json()["id"], two_masters["vis-m1"]["id"])
    listed = {x["id"]: x["repairs_count"] for x in client.get(
        "/api/repairs/clients/list", headers=m1).json()}
    assert own.json()["client_id"] in listed

    # старшая роль видит всех клиентов
    admin_listed = {x["id"] for x in client.get(
        "/api/repairs/clients/list", headers=operator_headers).json()}
    assert foreign_client in admin_listed


def test_master_client_lookup_returns_only_visible_repairs(
    client, operator_headers, two_masters, city_id
):
    """Поиск клиента по телефону не отдаёт мастеру чужие заказы этого клиента.

    Проверены обе ветки: единственный клиент (список его ремонтов) и несколько
    совпадений (счётчики ремонтов у кандидатов).
    """
    # два ремонта одного клиента: один назначен vis-m1, другой — vis-m2
    a = _intake(client, operator_headers, city_id, "vis-19", phone="+993 61 500019")
    assert a.status_code == 201, a.text
    b = _intake(client, operator_headers, city_id, "vis-20", phone="+993 61 500019")
    assert b.status_code == 201, b.text
    _assign(client, operator_headers, a.json()["id"], two_masters["vis-m1"]["id"])
    _assign(client, operator_headers, b.json()["id"], two_masters["vis-m2"]["id"])

    # клиент, у которого нет ни одного доступного vis-m1 ремонта
    hidden = _intake(client, operator_headers, city_id, "vis-21", phone="+993 61 509977")
    assert hidden.status_code == 201, hidden.text
    _assign(client, operator_headers, hidden.json()["id"], two_masters["vis-m2"]["id"])

    m1 = _bearer(client, "vis-m1@msb.local")

    # такому клиенту имя и телефон не раскрываются
    hid = client.get(
        "/api/repairs/clients/lookup", headers=m1, params={"phone": "+993 61 509977"}
    )
    assert hid.status_code == 200, hid.text
    assert hid.json().get("found") is False, hid.text[:300]
    assert "client" not in hid.json(), hid.text[:300]
    # старшая роль того же клиента находит
    assert client.get(
        "/api/repairs/clients/lookup", headers=operator_headers,
        params={"phone": "+993 61 509977"}).json()["found"] is True

    r = client.get(
        "/api/repairs/clients/lookup", headers=m1, params={"phone": "+993 61 500019"}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    ids = {x["id"] for x in data["repairs"]}
    assert a.json()["id"] in ids, "свой заказ не вернулся"
    assert b.json()["id"] not in ids, "чужой заказ вернулся мастеру"
    assert data["repairs_count"] == 1, data["repairs_count"]

    # Ветка с несколькими совпадениями: счётчик считается только по доступным
    # мастеру ремонтам, поэтому у клиента с чужим заказом он меньше полного.
    # Номера берём из незанятого префикса 5099: база в тестах общая для сессии,
    # и широкий поиск зацепил бы клиентов из других тестов.
    SEARCH = "61 5099"
    for i in range(3):
        c_i = _intake(client, operator_headers, city_id, f"vis-cand-{i}",
                      phone=f"+993 61 5099{10 + i}")
        assert c_i.status_code == 201, c_i.text
        # второй ремонт того же клиента уходит другому мастеру
        extra = _intake(client, operator_headers, city_id, f"vis-cand-x-{i}",
                        phone=f"+993 61 5099{10 + i}")
        assert extra.status_code == 201, extra.text
        _assign(client, operator_headers, extra.json()["id"], two_masters["vis-m2"]["id"])

    cand = client.get(
        "/api/repairs/clients/lookup", headers=m1, params={"phone": SEARCH}
    )
    assert cand.status_code == 200, cand.text
    assert cand.json().get("multiple") is True, cand.text[:300]
    rows = {r["phone"]: r["repairs_count"] for r in cand.json()["candidates"]}
    assert len(rows) == 3, rows
    for phone, count in rows.items():
        assert count == 1, (phone, count, rows)

    # старшая роль видит оба ремонта каждого клиента
    admin_rows = {r["phone"]: r["repairs_count"] for r in client.get(
        "/api/repairs/clients/lookup", headers=operator_headers,
        params={"phone": SEARCH}).json()["candidates"]}
    for phone in rows:
        assert admin_rows[phone] == 2, (phone, admin_rows[phone])


def test_master_clients_suggest_hides_foreign_clients(
    client, operator_headers, two_masters, city_id
):
    """Автокомплит заказчика не подсказывает мастеру владельцев чужих заказов.

    Эндпоинт доступен любому сотруднику, который открывает приёмку, и раньше
    отдавал имена и телефоны всех клиентов сервиса.
    """
    # Имена берём уникальные: подсказка ограничена восемью строками, и широкий
    # поиск по общему имени в общей для сессии базе давал бы непредсказуемый срез.
    hidden = _intake(client, operator_headers, city_id, "vis-22",
                     phone="+993 61 509988", name="ЧужойПодсказка509988")
    assert hidden.status_code == 201, hidden.text
    _assign(client, operator_headers, hidden.json()["id"], two_masters["vis-m2"]["id"])

    mine = _intake(client, operator_headers, city_id, "vis-23",
                   phone="+993 61 509989", name="СвойПодсказка509989")
    assert mine.status_code == 201, mine.text
    _assign(client, operator_headers, mine.json()["id"], two_masters["vis-m1"]["id"])

    cookies = _login(client, "vis-m1@msb.local")

    # поиск по имени своего клиента — находится
    r = client.get("/web/clients-suggest", cookies=cookies,
                   params={"q": "СвойПодсказка509989"})
    assert r.status_code == 200, r.text
    assert {row["phone"] for row in r.json()} == {"+993 61 509989"}, r.text

    # поиск по имени чужого клиента — пусто
    r2 = client.get("/web/clients-suggest", cookies=cookies,
                    params={"q": "ЧужойПодсказка509988"})
    assert r2.status_code == 200, r2.text
    assert r2.json() == [], r2.text

    # поиск по цифрам чужого номера — тоже пусто
    r3 = client.get("/web/clients-suggest", cookies=cookies, params={"q": "509988"})
    assert r3.status_code == 200, r3.text
    assert r3.json() == [], r3.text

    # старшая роль видит обоих
    admin_cookies = _login(client, "operator@msb.local", "operator123")
    r4 = client.get("/web/clients-suggest", cookies=admin_cookies, params={"q": "50998"})
    assert r4.status_code == 200, r4.text
    admin_phones = {row["phone"] for row in r4.json()}
    assert {"+993 61 509988", "+993 61 509989"} <= admin_phones, admin_phones
