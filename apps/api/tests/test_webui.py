"""Smoke-тесты серверного веб-интерфейса на Jinja2 (замена React/Next.js).

Проверяем, что страницы рендерятся, авторизация идёт через httpOnly-cookie,
мастер не попадает в админ-разделы, а публичная страница не отдаёт внутренние
данные. Бизнес-логика — та же, что у JSON-API (покрыта 186 тестами).

Используем общую фикстуру `client` из conftest (засеяны admin/operator/master).
"""
import pytest


def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return r.cookies


def test_login_page_renders_anon(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "MSB" in r.text and 'name="password"' in r.text


def test_protected_page_redirects_anon(client):
    r = client.get("/repairs", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


def test_login_sets_http_only_cookies(client):
    r = client.post(
        "/login", data={"email": "admin@msb.local", "password": "admin123"},
        follow_redirects=False,
    )
    cookies = r.headers.get("set-cookie", "")
    assert "msb_access=" in cookies
    assert "httponly" in cookies.lower()


def test_bad_password_shows_error(client):
    r = client.post(
        "/login", data={"email": "admin@msb.local", "password": "wrong"},
        follow_redirects=False,
    )
    assert r.status_code == 401
    assert "Неверный email или пароль" in r.text


def test_logout_clears_session(client):
    client.post("/login", data={"email": "admin@msb.local", "password": "admin123"})
    r = client.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    # После выхода защищённая страница снова уводит на логин.
    assert client.get("/repairs", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("path", [
    "/repairs", "/repairs/new", "/clients", "/callcenter",
    "/parts", "/prices", "/notifications", "/dashboard", "/profile",
    "/chat", "/admin/users",
])
def test_all_main_pages_render_for_admin(client, path):
    cookies = _login(client)
    r = client.get(path, cookies=cookies)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:300]}"


def test_intake_flow_creates_repair_and_redirects_to_list(client):
    """Приёмка: после сохранения — редирект в список ремонтов с окном подтверждения."""
    cookies = _login(client)
    cities = client.get("/api/lookups/cities", cookies=cookies).json()
    r = client.post("/repairs/new", cookies=cookies, data={
        "city_id": cities[0]["id"],
        "full_name": "Веб Тестов",
        "phone": "+993 61 7778899",
        "device_type": "Телевизоры",
        "brand": "Samsung",
        "model": "QE55",
        "fault_client": "не включается",
        "consent_pdn": "1",
        "consent_storage": "1",
    }, follow_redirects=False)
    assert r.status_code == 303, r.text
    location = r.headers["location"]
    assert location.startswith("/repairs?just=accepted"), location
    page = client.get(location, cookies=cookies)
    assert page.status_code == 200
    assert "Samsung" in page.text and "QE55" in page.text
    assert "Сохранено" in page.text  # окно подтверждения на списке ремонтов


def test_intake_autoprints_label_not_blank(client, admin_headers):
    """При приёмке автоматически ставится в очередь ЭТИКЕТКА (repair_label), а не бланк."""
    cookies = _login(client)
    # Включаем CUPS-принтер этикеток — иначе автопечать молча пропускается.
    r = client.post("/admin/settings/label", cookies=cookies, data={
        "label_name": "Zebra_58",
        "label_ip": "192.168.5.99",
        "label_port": "631",
        "label_media": "Custom.58x38mm",
    }, follow_redirects=False)
    assert r.status_code == 303, r.text

    cities = client.get("/api/lookups/cities", cookies=cookies).json()
    r = client.post("/repairs/new", cookies=cookies, data={
        "city_id": cities[0]["id"],
        "full_name": "Этикетка Тест",
        "phone": "+993 61 0001122",
        "device_type": "Телевизоры",
        "brand": "LG",
        "model": "50UP",
        "fault_client": "нет изображения",
        "consent_pdn": "1",
        "consent_storage": "1",
    }, follow_redirects=False)
    assert r.status_code == 303, r.text

    jobs = client.get("/api/print/jobs", headers=admin_headers).json()
    labels = [j for j in jobs if (j.get("payload") or {}).get("document_kind") == "repair_label"]
    assert labels, "после приёмки в очереди печати должна быть этикетка"
    assert all((j.get("payload") or {}).get("printer", {}).get("mode") == "cups_remote" for j in labels)


def test_board_view_renders(client):
    cookies = _login(client)
    r = client.get("/repairs?view=board", cookies=cookies)
    assert r.status_code == 200
    assert "kanban" in r.text or "kcol" in r.text


def test_repairs_table_compact_columns_and_hints(client):
    """Таблица «Все ремонты»: 10 компактных колонок с эмодзи, кнопки-пояснения
    «?» у каждой, в «Итог» — бейдж оплаты."""
    cookies = _login(client)
    cities = client.get("/api/lookups/cities", cookies=cookies).json()
    r = client.post("/repairs/new", cookies=cookies, data={
        "city_id": cities[0]["id"],
        "full_name": "Колонка Клиент",
        "phone": "+993 63 5556677",
        "device_type": "Телевизоры",
        "brand": "LG",
        "model": "UQ80",
        "fault_client": "полосы на экране",
        "consent_pdn": "1", "consent_storage": "1",
    }, follow_redirects=False)
    assert r.status_code == 303, r.text

    page = client.get("/repairs", cookies=cookies)
    html = page.text
    for header in ("📅 Дата", "📺 Техника", "🧾 Принял", "🔧 Причина", "💵 Сумма",
                   "🔩 Запчасти", "👤 Клиент", "👷 Мастера", "💰 Выплата", "🏁 Итог"):
        assert header in html, header
    # Кнопка-пояснение «?» у каждой колонки (data-colhint).
    assert html.count("data-colhint") >= 10
    # Данные созданного ремонта и бейдж оплаты «долг» (не оплачен).
    assert "LG" in html
    assert "Колонка Клиент" in html
    assert "долг" in html


def test_public_status_page_has_no_internal_data(client):
    cookies = _login(client)
    cities = client.get("/api/lookups/cities", cookies=cookies).json()
    r = client.post("/repairs/new", cookies=cookies, data={
        "city_id": cities[0]["id"],
        "full_name": "Публик Клиент",
        "phone": "+993 62 0001122",
        "device_type": "Другое",
        "fault_client": "неисправность клиента",
        "consent_pdn": "1", "consent_storage": "1",
    }, follow_redirects=False)
    assert r.headers["location"].startswith("/repairs?just=accepted")
    items = client.get("/api/repairs?q=Публик Клиент", cookies=cookies).json()["items"]
    rid = items[0]["id"]
    repair = client.get(f"/api/repairs/{rid}", cookies=cookies).json()
    pub = client.get(f"/r/{repair['public_token']}")
    assert pub.status_code == 200
    assert repair["number"] in pub.text
    # Внутренних данных и имени клиента на публичной странице нет.
    assert "fault_master" not in pub.text
    assert "Публик Клиент" not in pub.text


def test_master_blocked_from_admin_users(client):
    # master@msb.local засеян фикстурой conftest.
    r = client.post("/login", data={"email": "master@msb.local", "password": "master123"},
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/admin/users", cookies=r.cookies, follow_redirects=False)
    assert page.status_code in (403, 303)


def test_chat_message_sent_via_html_form(client):
    """Отправка сообщения — обычная HTML-форма (POST /chat/send -> 303 -> HTML),
    без fetch/JSON в браузере."""
    cookies = _login(client)
    # Открываем чат, берём id первого канала.
    import re

    page = client.get("/chat", cookies=cookies)
    assert page.status_code == 200
    m = re.search(r'name="channel_id"\s+value="([0-9a-f-]{36})"', page.text)
    assert m, "не найдена форма отправки сообщения"
    channel_id = m.group(1)
    r = client.post("/chat/send", cookies=cookies, data={
        "channel_id": channel_id, "text": "HTML-сообщение регресс",
    }, follow_redirects=False)
    assert r.status_code == 303
    # После редиректа (GET) страница чата — это text/html и содержит сообщение.
    target = r.headers["location"]
    after = client.get(target, cookies=cookies)
    assert after.status_code == 200
    assert "text/html" in after.headers["content-type"]
    assert "HTML-сообщение регресс" in after.text


def test_every_navigable_page_is_html(client):
    """Все страницы, доступные в браузере (GET), отдают text/html."""
    cookies = _login(client)
    paths = [
        "/", "/repairs", "/repairs?view=board", "/repairs/new", "/clients",
        "/callcenter", "/parts", "/prices", "/notifications", "/dashboard",
        "/chat", "/admin/users", "/profile", "/login",
    ]
    for path in paths:
        r = client.get(path, cookies=cookies, follow_redirects=True)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        assert "text/html" in r.headers["content-type"], f"{path} отдаёт {r.headers['content-type']}"


def test_master_can_open_repairs_list(client):
    r = client.post("/login", data={"email": "master@msb.local", "password": "master123"},
                    follow_redirects=False)
    page = client.get("/repairs", cookies=r.cookies)
    assert page.status_code == 200


def test_notifications_page_renders_and_mark_read(client):
    """Страница уведомлений отдаёт HTML и доступна любому сотруднику."""
    cookies = _login(client)
    r = client.get("/notifications", cookies=cookies)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # «Прочитать все» без непрочитанных — корректный PRG-редирект.
    rr = client.post("/notifications/read-all", cookies=cookies, follow_redirects=False)
    assert rr.status_code == 303
    assert rr.headers["location"] == "/notifications"


def test_parts_page_has_equipment_section(client):
    """Склад показывает блок купленной техники (доноров)."""
    cookies = _login(client)
    r = client.post("/equipment/create", cookies=cookies, data={
        "name": "LG 32 — донор", "brand": "LG", "purchase_price": "120",
        "storage_place": "Полка 1",
    }, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/parts", cookies=cookies)
    assert page.status_code == 200
    assert "LG 32" in page.text


def test_prices_page_and_create(client):
    """Прайс-лист: страница и форма добавления позиции."""
    cookies = _login(client)
    r = client.post("/prices/create", cookies=cookies, data={
        "device_type": "Телевизоры", "fault": "Замена разъёма питания",
        "price_min": "100", "price_max": "250", "price_avg": "180",
    }, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/prices", cookies=cookies)
    assert page.status_code == 200
    assert "Замена разъёма питания" in page.text


def test_admin_settings_page_sections(client):
    """Страница настроек доступна админу во всех вкладках и отдаёт HTML."""
    cookies = _login(client)
    for section in ("general", "printer", "sms", "print", "ip"):
        r = client.get(f"/admin/settings?section={section}", cookies=cookies)
        assert r.status_code == 200, f"{section}: {r.status_code}"
        assert "text/html" in r.headers["content-type"]


def test_admin_settings_save_print_stub(client):
    """Вкладка «Печать» сохраняет тексты талона клиента и юридические тексты."""
    cookies = _login(client)
    r = client.post("/admin/settings/print", cookies=cookies, data={
        "legal_text": "Хранение 3 месяца.",
        "consent_repair_text": "Согласен на ремонт.",
        "stub_title": "ДЛЯ КЛИЕНТА",
        "stub_terms_label": "Условия:",
        "stub_consent_label": "О ремонте:",
        "stub_qr_caption": "Скан QR",
        "stub_sign_client": "Клиент",
        "stub_sign_date": "Число",
        "stub_cut_hint": "— резать здесь —",
        "intake_auto_print": "both",
    }, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/admin/settings?section=print", cookies=cookies)
    assert "ДЛЯ КЛИЕНТА" in page.text
    assert "Хранение 3 месяца." in page.text
    assert "Согласен на ремонт." in page.text
    assert 'value="both" selected' in page.text


def test_admin_settings_save_printer_and_general(client):
    cookies = _login(client)
    r = client.post("/admin/settings/printer", cookies=cookies, data={
        "printer_mode": "agent", "printer_name": "EPSON_TEST", "printer_port": "631",
    }, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/admin/settings?section=printer", cookies=cookies)
    assert "EPSON_TEST" in page.text
    r2 = client.post("/admin/settings/general", cookies=cookies, data={
        "brand_name": "MSB", "storage_months": "5",
        "currency_code": "TMT", "currency_symbol": "ман.", "currency_decimals": "0",
    }, follow_redirects=False)
    assert r2.status_code == 303


def test_admin_settings_requires_admin(client):
    """Обычный сотрудник (master) не получает доступ к настройкам."""
    r = client.post("/login", data={"email": "master@msb.local", "password": "master123"},
                    follow_redirects=False)
    page = client.get("/admin/settings", cookies=r.cookies, follow_redirects=False)
    assert page.status_code in (403, 303)


def test_intake_rich_form_fields(client):
    """Богатая форма приёмки: экран выбора + все поля эталона рендерятся."""
    cookies = _login(client)
    r = client.get("/repairs/new", cookies=cookies)
    assert r.status_code == 200
    assert "Выберите тип техники" in r.text
    f = client.get("/repairs/new?type=Телевизоры", cookies=cookies)
    assert f.status_code == 200
    for marker in ('data-tv-intake', 'name="equipment"', 'name="condition"',
                   'data-delivery-open', 'data-camera-open', 'name="contact2_relation"',
                   'name="fault_client"', 'name="delivery_district"'):
        assert marker in f.text, marker


def test_intake_monitors_and_boxes_get_own_numbers(client, admin_headers):
    """Карточки «Мониторы» / «ТВ-приставки» получают MN-/BX-, а не общий RE-."""
    cookies = _login(client)
    cities = client.get("/api/lookups/cities", cookies=cookies).json()
    city_id = cities[0]["id"]

    picker = client.get("/repairs/new", cookies=cookies)
    assert picker.status_code == 200
    assert "/repairs/new?type=Мониторы" in picker.text
    assert "/repairs/new?type=ТВ-приставки" in picker.text

    form = client.get("/repairs/new?type=Мониторы", cookies=cookies)
    assert form.status_code == 200
    assert 'name="device_type"' in form.text
    assert "Мониторы" in form.text

    cases = [
        ("Мониторы", "Dell", "P2419H", "+993 61 3334455", "MN-"),
        ("ТВ-приставки", "Xiaomi", "MiBoxS", "+993 61 3334466", "BX-"),
    ]
    for device_type, brand, model, phone, prefix in cases:
        r = client.post("/repairs/new", cookies=cookies, data={
            "city_id": city_id,
            "full_name": f"Клиент {device_type}",
            "phone": phone,
            "device_type": device_type,
            "brand": brand,
            "model": model,
            "fault_client": "не включается",
            "consent_pdn": "1",
            "consent_storage": "1",
        }, follow_redirects=False)
        assert r.status_code == 303, r.text
        items = client.get(
            f"/api/repairs?q={model}", headers=admin_headers,
        ).json()["items"]
        assert items, f"ремонт {device_type} не найден"
        assert items[0]["number"].startswith(prefix), items[0]["number"]
        assert items[0]["device_type"] == device_type


def test_intake_create_persists_archive_fields(client, admin_headers):
    """Приёмка сохраняет комплектацию, состояние, доставку и второй контакт."""
    cookies = _login(client)
    # узнаём city_id из формы
    page = client.get("/repairs/new?type=Телевизоры", cookies=cookies).text
    import re
    m = re.search(r'name="city_id" value="([0-9a-f-]+)"', page)
    cid = m.group(1)
    r = client.post("/repairs/new", cookies=cookies, data={
        "city_id": cid, "device_type": "Телевизоры",
        "brand_manual": "LG", "model_manual": "OLED55", "serial_manual": "SN-ARCH-9",
        "equipment": ["remote", "power_cable"], "equipment_other": "документы",
        "condition": ["screen_scratches"], "condition_other": "скол корпуса",
        "fault_client": "не включается",
        "full_name": "Архив Тест", "phone": "+99361000000",
        "contact2_name": "Второй", "contact2_phone": "+99362000000",
        "contact2_relation": "Доставщик",
        "is_delivery": "1", "delivery_district": "Парахат 1",
        "consent_pdn": "1", "consent_storage": "1", "consent_repair": "1",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/repairs?just=accepted")

    # Ремонт создан — ищем его по серийнику и проверяем сохранённые поля.
    items = client.get("/api/repairs?q=SN-ARCH-9", headers=admin_headers).json()["items"]
    assert items, "ремонт не найден после приёмки"
    repair = items[0]
    assert repair["brand"] == "LG" and repair["model"] == "OLED55"
    comp = repair.get("complectation") or {}
    assert "Пульт" in comp and "Шнур питания" in comp and "документы" in comp
    assert repair.get("condition_notes") and "Царапины на экране" in repair["condition_notes"]
    assert repair.get("is_delivery") is True
    assert repair.get("contact2_name") == "Второй"
    assert repair.get("contact2_phone") == "+99362000000"


def test_admin_logs_monitor(client):
    cookies = _login(client)
    r = client.get("/admin/logs", cookies=cookies)
    assert r.status_code == 200
    assert "Мониторинг логов" in r.text
    assert 'id="log-monitor"' in r.text
    # Live-обновление — по SSE (стрим), fallback — фрагмент для опроса.
    assert "data-sse-url" in r.text
    assert "pause-btn" in r.text
    # HTML-фрагмент для автообновления тоже отдаётся
    r2 = client.get("/admin/logs/panel", cookies=cookies)
    assert r2.status_code == 200
    assert "log-window" in r2.text


def test_admin_logs_forbidden_for_master(client):
    cookies = _login(client, "master@msb.local", "master123")
    r = client.get("/admin/logs", cookies=cookies)
    assert r.status_code == 403


def test_admin_logs_view_grant_for_non_admin(client, admin_headers):
    """Право «Мониторинг логов» как отдельная функция: не-админ с грантом видит
    страницу, но НЕ управление журналом (настройки/очистка — только admin)."""
    r = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Тестовый аудитор",
            "email": "auditor@msb.local",
            "password": "auditor123",
            "role": "callcenter",
            "permissions": ["logs"],
        },
    )
    assert r.status_code == 201, r.text

    cookies = _login(client, "auditor@msb.local", "auditor123")
    assert client.get("/admin/logs", cookies=cookies).status_code == 200
    assert client.get("/admin/logs/panel", cookies=cookies).status_code == 200
    # Управление журналом — только администратор.
    assert client.get("/admin/logs/settings", cookies=cookies).status_code == 403
    assert client.post("/admin/logs/clear", cookies=cookies).status_code == 403


def test_admin_logs_settings_admin_only(client):
    master = _login(client, "master@msb.local", "master123")
    assert client.get("/admin/logs/settings", cookies=master).status_code == 403
    admin = _login(client)
    r = client.get("/admin/logs/settings", cookies=admin)
    assert r.status_code == 200
    assert "Настройки журнала" in r.text


def test_admin_logs_search(client):
    admin = _login(client)
    # Поиск по тексту (grep) в фрагменте.
    r = client.get("/admin/logs/panel?q=msb", cookies=admin)
    assert r.status_code == 200
    assert "log-window" in r.text
    # Спецсимволы в запросе не ломают рендер.
    assert client.get("/admin/logs/panel?q=%D0%BE%D1%88%D0%B8%D0%B1%D0%BA%D0%B0", cookies=admin).status_code == 200


def test_admin_logs_stream_forbidden_for_master(client):
    master = _login(client, "master@msb.local", "master123")
    r = client.get("/admin/logs/stream", cookies=master)
    assert r.status_code == 403
