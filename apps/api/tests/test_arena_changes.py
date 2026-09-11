"""Проверка пакета правок: приёмка (мастер/автокомплит), список, доска, этикетки."""

import base64
import re

import pytest


@pytest.fixture(autouse=True)
def _clean_cookie_jar(client):
    """Не тащить наши логины в соседние тесты: session-scoped `client` общий,
    а cookie-банка у него одна. После каждого теста возвращаем её анонимной."""
    yield
    client.cookies.clear()


def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return dict(r.cookies)


LABEL_CONFIG = {
    "ip": "192.168.5.238",
    "port": 631,
    "mode": "cups_remote",
    "name": "3B-350B",
    "width_mm": 58,
    "height_mm": 38,
    "media": "Custom.58x38mm",
}


def _configure_label_printer(client, admin_headers):
    r = client.put("/api/admin/printer/label", headers=admin_headers, json=LABEL_CONFIG)
    assert r.status_code == 200, r.text


def _make_repair(client, admin_headers, key, name, phone):
    r = client.post(
        "/api/repairs",
        headers={**admin_headers, "Idempotency-Key": key},
        json={
            "city_id": _city_id(client, admin_headers),
            "client": {"full_name": name, "phone": phone, "consent_pdn": True},
            "device_type": "Телевизоры", "brand": "TCL", "model": "32S",
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _city_id(client, admin_headers):
    return client.get("/api/lookups/cities", headers=admin_headers).json()[0]["id"]


# ---------------------------------------------------------------- приёмка
def test_intake_form_has_master_select_for_admin(client):
    cookies = _login(client)
    page = client.get("/repairs/new?type=Телевизоры", cookies=cookies)
    assert page.status_code == 200, page.text
    # Карточка заказчика теперь первая.
    assert page.text.index("Заказчик") < page.text.index("Марка — Модель — SN")
    # Админу поле мастера видно.
    assert 'name="master_id"' in page.text
    # Города/филиала в видимой форме нет (только скрытое служебное поле).
    assert 'name="city_id_select"' not in page.text
    assert "Город / филиал" not in page.text
    # Автокомплит и кнопка телефонной книги подключены.
    assert "clients-suggest" in page.text
    assert "data-phonebook" in page.text


def test_intake_form_hides_master_select_for_master(client):
    cookies = _login(client, "master@msb.local", "master123")
    page = client.get("/repairs/new?type=Телевизоры", cookies=cookies)
    assert page.status_code == 200, page.text
    assert 'name="master_id"' not in page.text
    assert "назначит администратор или оператор" in page.text


def test_intake_by_master_ignores_master_id_in_form(client, admin_headers):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    master = next(u for u in users if u["email"] == "master@msb.local")

    cookies = _login(client, "master@msb.local", "master123")
    page = client.get("/repairs/new?type=Телевизоры", cookies=cookies)
    cid = re.search(r'name="city_id" value="([0-9a-f-]+)"', page.text).group(1)
    r = client.post(
        "/repairs/new",
        cookies=cookies,
        data={
            "city_id": cid,
            "device_type": "Телевизоры",
            "identity_raw": "LG-55UP-SN777",
            "full_name": "Клиент Без Назначения",
            "phone": "+993 61 000 111",
            "master_id": str(master["id"]),  # попытка подсунуть мастера из формы
            "fault_client": "нет звука",
            "consent_pdn": "on",
            "consent_storage": "on",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    # Ремонт создан НОВЫМ (статус «Принято») и без исполнителя.
    items = client.get(
        "/api/repairs?q=Клиент Без Назначения", headers=admin_headers
    ).json()["items"]
    assert items, "ремонт не создан"
    rep = items[0]
    assert rep["status"] == "Принято", rep
    assert rep["master_id"] is None, rep
    # В списке мастера этот ремонт не виден (он ему не назначен).
    master_page = client.get("/repairs", cookies=cookies)
    assert "Клиент Без Назначения" not in master_page.text


# ------------------------------------------------------- автокомплит клиента
def test_clients_suggest_finds_by_phone_and_name(client, admin_headers):
    _make_repair(client, admin_headers, "suggest-1", "Автокомплит Тестов", "+993 65 123456")
    cookies = _login(client)
    by_phone = client.get("/web/clients-suggest?q=65123", cookies=cookies)
    assert by_phone.status_code == 200
    assert any(x["name"] == "Автокомплит Тестов" for x in by_phone.json()), by_phone.json()
    by_name = client.get("/web/clients-suggest?q=Автокомп", cookies=cookies)
    assert any("65 123456" in (x["phone"] or "") for x in by_name.json()), by_name.json()
    # Анониму — 401 (сбрасываем cookie-банку TestClient — иначе тащит старую сессию).
    client.cookies.clear()
    anon = client.get("/web/clients-suggest?q=65123")
    assert anon.status_code == 401


# ------------------------------------------------------------------- список
def test_list_has_perpage_selector_and_no_number_anywhere(client, admin_headers):
    rep = _make_repair(client, admin_headers, "nonum-1", "Номер Скрыт", "+993 61 121212")
    cookies = _login(client)
    page = client.get("/repairs?per_page=100", cookies=cookies)
    assert page.status_code == 200
    assert "На странице" in page.text
    assert 'name="per_page"' in page.text
    # Номер ремонта не отображается нигде: ни под датой, ни в других колонках,
    # ни в aria/слуховых подписях — и на доске тоже.
    assert rep["number"] not in page.text
    assert 'class="code">' not in page.text
    board = client.get("/repairs?view=board", cookies=cookies)
    assert rep["number"] not in board.text


def test_list_inline_edit_marks_for_admin_and_not_for_master(client):
    admin_page = client.get("/repairs", cookies=_login(client))
    assert "data-edit=" in admin_page.text
    assert "MSB_MASTERS" in admin_page.text
    master_page = client.get(
        "/repairs", cookies=_login(client, "master@msb.local", "master123")
    )
    assert "data-edit=" not in master_page.text
    assert "MSB_MASTERS" not in master_page.text


def test_list_row_does_not_navigate_on_single_click(client):
    page = client.get("/repairs", cookies=_login(client))
    assert "location.href='/repairs/" not in page.text
    assert 'class="clickable"' not in page.text


# -------------------------------------------------------------------- доска
def test_board_excludes_finished_and_keeps_three_columns(client, admin_headers):
    rep = _make_repair(client, admin_headers, "board-done-1", "Доска Готовый", "+993 61 555000")
    client.patch(
        f"/api/repairs/{rep['id']}", headers=admin_headers,
        json={"status": "Готово к выдаче"},
    )
    cookies = _login(client)
    board = client.get("/repairs?view=board", cookies=cookies)
    assert board.status_code == 200
    assert "Доска Готовый" not in board.text
    assert board.text.count('class="kcol"') == 3, "на доске должно быть 3 колонки"
    # А в таблице на этапе «Завершены» он есть.
    table = client.get("/repairs?stage=done", cookies=cookies)
    assert "Доска Готовый" in table.text


# ------------------------------------------------- клиентская этикетка (QR)
def test_client_label_job_created_and_pdf_is_valid(client, admin_headers):
    _configure_label_printer(client, admin_headers)
    rep = _make_repair(client, admin_headers, "clabel-1", "QR Клиент", "+993 61 777888")
    job = client.post(f"/api/repairs/{rep['id']}/print-client-label", headers=admin_headers)
    assert job.status_code == 200, job.text
    data = job.json()
    assert "/r/" in data["status_url"]
    pdf = base64.b64decode(data["pdf_base64"])
    assert pdf.startswith(b"%PDF")

    jobs = client.get("/api/print/jobs", headers=admin_headers).json()
    kinds = {j["template_id"] for j in jobs if j["repair_id"] == rep["id"]}
    assert "client-label-58x38" in kinds


def test_intake_queues_two_labels(client, admin_headers):
    _configure_label_printer(client, admin_headers)
    cookies = _login(client)
    page = client.get("/repairs/new?type=Телевизоры", cookies=cookies)
    cid = re.search(r'name="city_id" value="([0-9a-f-]+)"', page.text).group(1)
    r = client.post(
        "/repairs/new",
        cookies=cookies,
        data={
            "city_id": cid, "device_type": "Телевизоры",
            "identity_raw": "PHILIPS-43PUS-SN1",
            "full_name": "Две Этикетки", "phone": "+993 61 888999",
            "fault_client": "полосы", "consent_pdn": "on", "consent_storage": "on",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    items = client.get("/api/repairs?q=Две Этикетки", headers=admin_headers).json()["items"]
    rid = items[0]["id"]
    jobs = client.get("/api/print/jobs", headers=admin_headers).json()
    mine = [j for j in jobs if j["repair_id"] == rid and j["status"] == "queued"]
    kinds = {j["template_id"] for j in mine}
    assert {"repair-label-58x38", "client-label-58x38"} <= kinds, kinds


# ------------------------------------------------- публичная страница (QR)
def test_public_page_shows_storage_and_legal(client, admin_headers):
    rep = _make_repair(client, admin_headers, "pub-legal-1", "Публичность Проверов", "+993 61 999000")
    page = client.get(f"/r/{rep['public_token']}")
    assert page.status_code == 200
    assert "Условия хранения" in page.text
    assert "Юридическая информация" in page.text
    assert "Статус ремонта" in page.text


# ------------------------------------------------------ inline-правка полей
def test_field_endpoint_updates_master_payout(client, admin_headers):
    rep = _make_repair(client, admin_headers, "payout-1", "Выплата Проверов", "+993 61 333444")
    resp = client.post(
        f"/repairs/{rep['id']}/field",
        data={"field": "master_payout", "value": "150", "next": "/repairs"},
        cookies=_login(client),
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    out = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert float(out["master_payout"]) == 150.0
