"""Приёмка без аккаунта: страница /intake.

Технику может оформить человек без входа. Ремонт создаётся в статусе «Новый»,
без мастера, и попадает в общий список «Все ремонты» — дальше его берёт мастер
или назначает администратор. Принявший — служебная учётка «Приёмка без аккаунта».
"""
import re

import pytest


def _set_intake(client, admin_headers, *, enabled=True, code=""):
    """Настройка public_intake через админский API (как это делает админ в UI)."""
    r = client.put(
        "/api/admin/settings/public_intake",
        headers=admin_headers,
        json={"value": {"enabled": enabled, "code": code},
              "description": "Приёмка без аккаунта"},
    )
    assert r.status_code == 200, r.text
    return r


@pytest.fixture()
def intake_off(client, admin_headers):
    _set_intake(client, admin_headers, enabled=False)
    yield
    _set_intake(client, admin_headers, enabled=True)


@pytest.fixture()
def intake_code(client, admin_headers):
    _set_intake(client, admin_headers, enabled=True, code="СЕКРЕТ-2026")
    yield "СЕКРЕТ-2026"
    _set_intake(client, admin_headers, enabled=True, code="")


# Номера телефонов уникальны для этого файла: клиенты дедуплицируются по
# нормализованному номеру, а БД в тестах общая для всей сессии.
def _form(**overrides):
    data = {
        "city_id": "",
        "device_type": "Телевизоры",
        "identity_raw": "SAMSUNG-QE55Q70-SN123456",
        "phone": "+993 61 310001",
        "full_name": "Публичный Клиент",
        "fault_client": "не включается",
        "equipment": ["remote", "power_cable"],
        "condition": ["screen_scratches"],
        "condition_other": "трещина снизу",
        "consent_repair": "1",
        "consent_storage": "1",
        "consent_pdn": "1",
    }
    data.update(overrides)
    return data


def _number_from_done_page(html: str) -> str:
    """Номер ремонта со страницы подтверждения."""
    m = re.search(r"<h1>([^<]+)</h1>", html)
    assert m, html[:300]
    return m.group(1).strip()


def _submit(client, admin_headers, **overrides) -> dict:
    """Отправить публичную приёмку и вернуть созданный ремонт из «Все ремонты»."""
    r = client.post("/intake", data=_form(**overrides))
    assert r.status_code == 201, r.text[:500]
    number = _number_from_done_page(r.text)
    items = client.get("/api/repairs?page_size=100", headers=admin_headers).json()["items"]
    repair = next((i for i in items if i["number"] == number), None)
    assert repair is not None, f"ремонт {number} не появился в «Все ремонты»"
    return repair


def _ui_login(client):
    r = client.post(
        "/login",
        data={"email": "admin@msb.local", "password": "admin123", "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/login" not in r.headers["location"]
    return r


# --------------------------------------------------------------------------
# Страница доступна без входа
# --------------------------------------------------------------------------
def test_intake_first_shows_device_type_picker(client):
    """Без ?type= страница начинается с выбора техники — как обычная приёмка."""
    r = client.get("/intake")
    assert r.status_code == 200
    body = r.text
    assert "Выберите тип техники" in body
    assert 'name="phone"' not in body, "форма не должна открываться до выбора техники"
    # ссылки выбора ведут на публичную приёмку, а не на /repairs/new
    assert 'href="/intake?type=Телевизоры"' in body
    assert "/repairs/new?type=" not in body


def test_picker_lists_the_same_device_classes(client, admin_headers):
    """Категории те же, что видит сотрудник на /repairs/new."""
    public = client.get("/intake").text
    _ui_login(client)
    staff = client.get("/repairs/new").text
    for cls in ("Телевизоры", "Мониторы", "ТВ-приставки", "Компьютеры", "Другое"):
        assert f"/intake?type={cls}" in public
        assert f"/repairs/new?type={cls}" in staff


def test_form_opens_after_type_is_chosen(client):
    r = client.get("/intake?type=Телевизоры")
    assert r.status_code == 200
    body = r.text
    assert 'action="/intake"' in body
    assert 'name="phone"' in body
    assert "+993" in body                     # префикс подставлен
    assert 'name="full_name"' in body
    assert 'name="fault_client"' in body
    # внутренний интерфейс на странице не подключён
    assert "/repairs/new" not in body
    assert "Выйти" not in body


def test_public_form_has_no_master_selection(client):
    """Единственное отличие от обычной приёмки — нет выбора мастера."""
    public = client.get("/intake?type=Телевизоры").text
    assert 'name="master_id"' not in public
    assert "Мастер-исполнитель" not in public

    _ui_login(client)
    staff = client.get("/repairs/new?type=Телевизоры").text
    assert 'name="master_id"' in staff


def test_public_form_repeats_staff_form_fields(client):
    """Поля те же, что у сотрудника: техника, комплектация, состояние, фото."""
    public = client.get("/intake?type=Телевизоры").text
    for field in (
        'name="identity_raw"', 'name="equipment"', 'name="equipment_other"',
        'name="condition"', 'name="condition_other"', 'name="photos"',
        'name="contact2_phone"', 'name="delivery_district"',
    ):
        assert field in public, field


def test_client_autocomplete_is_disabled_for_anonymous(client):
    """Поиск по базе клиентов не должен работать без входа."""
    body = client.get("/intake?type=Телевизоры").text
    assert "data-no-clients-ac" in body

    # Эндпоинт подсказок закрыт для анонима. Клиент в тестах сессионный и может
    # нести cookie прошлого теста, поэтому берём чистый экземпляр.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, client=("127.0.0.1", 50000)) as anon:
        assert anon.cookies.get("msb_session") is None
        r = anon.get("/web/clients-suggest?q=иван")
        assert r.status_code == 401


def test_done_page_links_to_client_status_page(client, admin_headers, city_id):
    r = client.post("/intake", data=_form(city_id=city_id, phone="+993 61 310012"))
    assert r.status_code == 201
    href = re.search(r'class="link" href="(/r/[^"]+)"', r.text)
    assert href, "на странице подтверждения нет ссылки на статус"
    # ссылка рабочая и открывается без входа
    assert client.get(href.group(1)).status_code == 200


# --------------------------------------------------------------------------
# Создание ремонта
# --------------------------------------------------------------------------
def test_anonymous_intake_creates_repair(client, admin_headers, city_id):
    repair = _submit(client, admin_headers, city_id=city_id)
    assert repair["client_name"] == "Публичный Клиент"
    assert repair["device_type"] == "Телевизоры"
    assert repair["brand"] == "SAMSUNG"
    assert repair["model"] == "QE55Q70"
    assert repair["serial"] == "SN123456"


def test_created_repair_is_new_and_without_master(client, admin_headers, city_id):
    repair = _submit(client, admin_headers, city_id=city_id, phone="+993 61 310002")
    assert repair["status"] == "Новый"
    # исполнители в списке отдаются как master_ids / master_names
    assert repair["master_ids"] == [], "мастер не должен назначаться на публичной приёмке"
    assert repair["master_names"] == []


def test_repair_appears_in_new_filter(client, admin_headers, city_id):
    """Ремонт виден в разделе «Новые» списка «Все ремонты»."""
    repair = _submit(client, admin_headers, city_id=city_id, phone="+993 61 310013")
    r = client.get("/api/repairs?status=Новый&page_size=100", headers=admin_headers)
    assert r.status_code == 200
    numbers = [i["number"] for i in r.json()["items"]]
    assert repair["number"] in numbers


def test_master_cannot_be_assigned_through_public_form(client, admin_headers, city_id):
    """Даже если в форму подложить master_id — ремонт останется без мастера."""
    masters = client.get("/api/admin/users", headers=admin_headers).json()
    master = next((u for u in masters if u.get("role") == "master"), None)
    if master is None:
        pytest.skip("в базе нет мастера")
    repair = _submit(
        client, admin_headers, city_id=city_id, phone="+993 61 310003",
        master_id=master["id"],
    )
    assert repair["master_ids"] == []
    assert repair["master_names"] == []


def test_accepted_by_is_the_service_account(client, admin_headers, city_id):
    repair = _submit(client, admin_headers, city_id=city_id, phone="+993 61 310004")
    # в списке принятый сотрудник отдаётся именем
    assert repair.get("accepted_by_name") == "Приёмка без аккаунта"
    # и это служебная учётка, а не кто-то из сотрудников
    users = client.get("/api/admin/users", headers=admin_headers).json()
    svc = next(u for u in users if u["email"] == "intake@msb.local")
    assert repair["accepted_by"] == svc["id"]
    assert svc["active"] is False


def test_service_account_cannot_log_in(client):
    r = client.post(
        "/login",
        data={"email": "intake@msb.local", "password": "intake123", "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_complectation_and_condition_are_saved(client, admin_headers, city_id):
    repair = _submit(client, admin_headers, city_id=city_id, phone="+993 61 310005")
    detail = client.get(f"/api/repairs/{repair['id']}", headers=admin_headers).json()
    comp = detail.get("complectation") or {}
    assert comp.get("Пульт") is True
    assert comp.get("Шнур питания") is True
    assert "Царапины на экране" in (detail.get("condition_notes") or "")
    assert "трещина снизу" in (detail.get("condition_notes") or "")


def test_delivery_is_saved(client, admin_headers, city_id):
    repair = _submit(
        client, admin_headers, city_id=city_id, phone="+993 61 310006",
        is_delivery="1", delivery_district="Парахат 3/2",
        delivery_comment="позвонить за час",
    )
    detail = client.get(f"/api/repairs/{repair['id']}", headers=admin_headers).json()
    assert detail.get("is_delivery") is True
    assert detail.get("delivery_district") == "Парахат 3/2"


def test_delivery_zero_is_not_delivery(client, admin_headers, city_id):
    repair = _submit(
        client, admin_headers, city_id=city_id, phone="+993 61 310007",
        is_delivery="0", delivery_district="Парахат",
    )
    detail = client.get(f"/api/repairs/{repair['id']}", headers=admin_headers).json()
    assert detail.get("is_delivery") is False
    assert not detail.get("delivery_district")


# --------------------------------------------------------------------------
# Валидация — правила те же, что на приёмке сотрудника
# --------------------------------------------------------------------------
@pytest.mark.parametrize("phone", ["", "+993 66 123456", "+993 61 12345", "12345"])
def test_bad_phone_is_rejected(client, phone):
    r = client.post("/intake", data=_form(phone=phone, city_id="x"), follow_redirects=False)
    assert r.status_code == 400
    assert "Номер телефона заказчика" in r.text


def test_bad_phone_does_not_create_repair(client, admin_headers, city_id):
    before = client.get("/api/repairs?page_size=1", headers=admin_headers).json()["total"]
    client.post("/intake", data=_form(phone="+993 66 310011", city_id=city_id))
    after = client.get("/api/repairs?page_size=1", headers=admin_headers).json()["total"]
    assert before == after


def test_missing_name_is_rejected(client, city_id):
    r = client.post("/intake", data=_form(full_name="  ", city_id=city_id))
    assert r.status_code == 400
    assert "имя и фамилию" in r.text.lower()


def test_missing_city_is_rejected(client):
    r = client.post("/intake", data=_form(city_id=""))
    assert r.status_code == 400
    assert "город" in r.text.lower()


def test_second_phone_is_validated_too(client, city_id):
    r = client.post("/intake", data=_form(city_id=city_id, contact2_phone="+993 66 123456"))
    assert r.status_code == 400
    assert "дополнительного контакта" in r.text


def test_form_is_refilled_after_error(client, city_id):
    r = client.post(
        "/intake",
        data=_form(city_id=city_id, phone="+993 66 123456", full_name="Ошибочный Клиент"),
    )
    assert r.status_code == 400
    assert "Ошибочный Клиент" in r.text, "введённые данные должны оставаться в форме"


# --------------------------------------------------------------------------
# Настройка: выключение и код доступа
# --------------------------------------------------------------------------
def test_disabled_intake_returns_404(client, intake_off):
    assert client.get("/intake").status_code == 404
    assert client.post("/intake", data=_form()).status_code == 404


def test_code_is_required_when_set(client, intake_code, admin_headers, city_id):
    # без кода — страница ввода кода, формы нет
    r = client.get("/intake")
    assert r.status_code == 200
    assert "Код доступа" in r.text
    assert 'name="full_name"' not in r.text

    # с кодом — выбор техники
    r = client.get("/intake?key=" + intake_code)
    assert r.status_code == 200
    assert "Выберите тип техники" in r.text

    # неверный код в GET — снова страница ввода
    r = client.get("/intake?key=неверный")
    assert "Выберите тип техники" not in r.text

    # отправка без кода — 403, ремонт не создан
    before = client.get("/api/repairs?page_size=1", headers=admin_headers).json()["total"]
    r = client.post("/intake", data=_form(city_id=city_id, phone="+993 61 310008"))
    assert r.status_code == 403
    assert "Неверный код доступа" in r.text
    after = client.get("/api/repairs?page_size=1", headers=admin_headers).json()["total"]
    assert before == after

    # отправка с кодом — создаёт
    r = client.post(
        "/intake",
        data=_form(city_id=city_id, phone="+993 61 310009", key=intake_code),
    )
    assert r.status_code == 201


# --------------------------------------------------------------------------
# Настройка в админке
# --------------------------------------------------------------------------
def test_admin_settings_section_renders(client, admin_headers):
    _ui_login(client)
    r = client.get("/admin/settings?section=intake")
    assert r.status_code == 200
    assert "Приёмка без аккаунта" in r.text
    assert 'name="public_intake_enabled"' in r.text
    assert 'name="public_intake_code"' in r.text


def test_admin_can_toggle_intake_from_ui(client, admin_headers):
    _ui_login(client)
    # выключаем
    r = client.post(
        "/admin/settings/public-intake",
        data={"public_intake_enabled": "0", "public_intake_code": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert client.get("/intake").status_code == 404

    # включаем с кодом
    r = client.post(
        "/admin/settings/public-intake",
        data={"public_intake_enabled": "1", "public_intake_code": "MSB-2026"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # адрес с кодом подсказан на странице настроек
    settings_page = client.get("/admin/settings?section=intake").text
    assert "/intake?key=MSB-2026" in settings_page

    # сама страница без кода закрыта, с кодом — открыта
    assert "Выберите тип техники" not in client.get("/intake").text
    assert "Выберите тип техники" in client.get("/intake?key=MSB-2026").text

    # возвращаем как было
    client.post(
        "/admin/settings/public-intake",
        data={"public_intake_enabled": "1", "public_intake_code": ""},
        follow_redirects=False,
    )
    assert "Выберите тип техники" in client.get("/intake").text


# --------------------------------------------------------------------------
# Обычная приёмка сотрудника не сломана общим парсером
# --------------------------------------------------------------------------
def test_staff_intake_still_works(client, admin_headers, city_id):
    # UI-форма приёмки работает по cookie-сессии, а не по Bearer-токену.
    _ui_login(client)
    r = client.post(
        "/repairs/new",
        data={
            "city_id": city_id,
            "device_type": "Мониторы",
            "identity_raw": "LG-27UP850-SN777",
            "phone": "+993 61 310010",
            "full_name": "Штатный Клиент",
            "fault_client": "нет изображения",
            "equipment": ["remote"],
            "condition": ["body_scratches"],
            "consent_repair": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:300]
    assert "/login" not in r.headers["location"], "форма отправила на логин"
    items = client.get("/api/repairs?page_size=100", headers=admin_headers).json()["items"]
    mine = [i for i in items if i["client_name"] == "Штатный Клиент"]
    assert mine, "ремонт штатной приёмки не найден"
    repair = mine[0]
    assert repair["brand"] == "LG"
    assert repair["model"] == "27UP850"
    assert repair["serial"] == "SN777"
    # штатная приёмка принимает от имени сотрудника, а не служебной учётки
    assert repair.get("accepted_by_name") != "Приёмка без аккаунта"
