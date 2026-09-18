"""Пакет правок: приёмка, список ремонтов и пять статусов.

Что здесь зафиксировано (по пунктам задачи):

1. Тип техники, выбранный на приёмке, печатается в ПРАВОМ ВЕРХНЕМ УГЛУ бланка,
   а не в поле «M_Model».
2. Мастер на приёмке назначает себя или оставляет поле пустым.
3. Мастера видят весь список ремонтов, берут свободные себе и добавляют
   напарников/помощников.
4. Кнопка «Доставка» на приёмке действительно отмечает доставку (раньше
   любой заказ считался привезённым) + необязательный комментарий.
5. В списке появилась колонка «Что починили» (со слов мастера).
6. Из вкладки «Все ремонты» убраны быстрые фильтры-этапы, заголовок и
   подсказка про двойной клик.
7. Статусов осталось пять; выдача техники — это `issued_at`, поэтому список
   подсвечивает «забрал, но не оплатил», а кнопка «Готово, но в сервисе»
   подсвечивает завершённые, которые до сих пор стоят в сервисе.
"""
import asyncio
import base64
import re
import uuid

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.db.models import DEFAULT_REPAIR_STATUSES, Repair
from app.db.session import async_session_factory


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return dict(r.cookies)


def _intake_form(client, cookies, **data):
    """POST /repairs/new с полями формы приёмки."""
    page = client.get("/repairs/new?type=Телевизоры", cookies=cookies)
    assert page.status_code == 200, page.text
    cid = re.search(r'name="city_id" value="([0-9a-f-]+)"', page.text).group(1)
    payload = {
        "city_id": cid,
        "device_type": "Телевизоры",
        "identity_raw": "SAMSUNG-QE55Q70-SN998877",
        "full_name": "Доставка Клиент",
        "phone": "+993 61 100002",
        "fault_client": "нет изображения",
        "consent_pdn": "on",
    }
    payload.update(data)
    r = client.post("/repairs/new", cookies=cookies, data=payload, follow_redirects=False)
    assert r.status_code == 303, r.text
    return payload


def _find(client, headers, phone):
    items = client.get(f"/api/repairs?q={phone}", headers=headers).json()["items"]
    assert items, f"ремонт не найден по {phone}"
    return items[0]


def _row_class(html):
    """Класс подсветки первой строки таблицы (без CSS-правил из <style>)."""
    m = re.search(r'<tr class="([^"]*)">', html)
    return m.group(1).strip() if m else ""


def _run(fn):
    async def _wrap():
        async with async_session_factory() as db:
            return await fn(db)

    return asyncio.run(_wrap())


@pytest.fixture(autouse=True)
def _clean_cookie_jar(client):
    yield
    client.cookies.clear()


# ---------------------------------------------------------------------------
# 1. Тип техники — в правом верхнем углу бланка
# ---------------------------------------------------------------------------
def _blank_text(client, headers, repair_id):
    r = client.post(f"/api/repairs/{repair_id}/print", headers=headers)
    assert r.status_code == 200, r.text
    pdf = base64.b64decode(r.json()["pdf_base64"])
    reader = PdfReader(__import__("io").BytesIO(pdf))
    return reader.pages[0].extract_text()


def test_blank_prints_device_type_outside_of_fields(client, admin_headers, operator_headers, city_id):
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "blank-devtype-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Бланк Тип", "phone": "+993 61 100001", "consent_pdn": True},
            "device_type": "Мониторы",
            "brand": "AOC",
            "model": "24B2XH",
            "fault_client": "нет подсветки",
        },
    )
    assert r.status_code == 201, r.text
    text = _blank_text(client, admin_headers, r.json()["id"])

    lines = text.splitlines()
    # Тип техники — отдельной строкой в самом верху бланка (правый верхний угол).
    assert "Мониторы" in lines[:3], lines[:5]
    # В поле «M_Model» его больше нет: там только марка и модель.
    mmodel = lines.index("M_Model:")
    assert "Мониторы" not in "".join(lines[mmodel:mmodel + 2])
    assert "AOC 24B2XH" in "".join(lines[mmodel:mmodel + 2]), lines[mmodel:mmodel + 3]


# ---------------------------------------------------------------------------
# 2. Мастер на приёмке: себя — можно, поле пустым — можно
# ---------------------------------------------------------------------------
def test_master_intake_can_leave_queue_or_pick_himself(client, admin_headers):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    master = next(u for u in users if u["email"] == "master@msb.local")
    cookies = _login(client, "master@msb.local", "master123")

    page = client.get("/repairs/new?type=Телевизоры", cookies=cookies)
    assert 'name="master_id"' in page.text
    assert "в очередь (не назначен)" in page.text

    # Пустое поле — ремонт новый, без исполнителя.
    _intake_form(client, cookies, full_name="Мастер Очередь", phone="+993 61 100003")
    rep = _find(client, admin_headers, "+993 61 100003")
    assert rep["master_id"] is None
    assert rep["status"] == "Новый"

    # Себя — сразу «На диагностике».
    _intake_form(
        client, cookies,
        full_name="Мастер Себя", phone="+993 61 100004",
        master_id=str(master["id"]),
    )
    rep = _find(client, admin_headers, "+993 61 100004")
    assert rep["master_id"] == master["id"]
    assert rep["status"] == "На диагностике"


# ---------------------------------------------------------------------------
# 3. Мастер видит весь список и берёт свободные заказы
# ---------------------------------------------------------------------------
def test_master_takes_free_repair_and_adds_helper(
    client, admin_headers, operator_headers, city_id
):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    master = next(u for u in users if u["email"] == "master@msb.local")
    helper = client.post(
        "/api/admin/users", headers=admin_headers,
        json={"name": "Помощник Список", "email": "helper-list@msb.local",
              "password": "pass123", "role": "master"},
    )
    assert helper.status_code == 201, helper.text

    free = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "free-take-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Свободный Клиент", "phone": "+993 61 100005", "consent_pdn": True},
            "device_type": "Телевизоры",
            "brand": "LG",
            "fault_client": "не включается",
        },
    )
    assert free.status_code == 201, free.text
    free_id = free.json()["id"]

    cookies = _login(client, "master@msb.local", "master123")
    page = client.get("/repairs?per_page=100", cookies=cookies)
    assert page.status_code == 200
    assert "Свободный Клиент" in page.text
    # Кнопка «Взять себя» показывается прямо в строке свободного ремонта.
    assert "Взять себе" in page.text

    taken = client.post(
        f"/repairs/{free_id}/assign",
        cookies=cookies,
        data={"master_ids": str(master["id"]), "next": "/repairs"},
        follow_redirects=False,
    )
    assert taken.status_code == 303, taken.text
    after = client.get(f"/api/repairs/{free_id}", headers=admin_headers).json()
    assert after["master_id"] == master["id"]
    assert after["status"] == "На диагностике"

    # Напарник + помощник к своему ремонту.
    r = client.patch(
        f"/api/repairs/{free_id}",
        headers={"Authorization": "Bearer " + client.post(
            "/api/auth/login",
            json={"email": "master@msb.local", "password": "master123"},
        ).json()["access_token"]},
        json={"helper_ids": [helper.json()["id"]]},
    )
    assert r.status_code == 200, r.text
    assert helper.json()["id"] in r.json()["helper_ids"]


def test_master_cannot_take_busy_repair(client, admin_headers, operator_headers, city_id):
    m1 = client.post(
        "/api/admin/users", headers=admin_headers,
        json={"name": "Мастер Занят", "email": "busy-master@msb.local",
              "password": "pass123", "role": "master"},
    ).json()
    busy = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "busy-take-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Занятый Клиент", "phone": "+993 61 100006", "consent_pdn": True},
            "device_type": "Телевизоры",
            "fault_client": "нет звука",
            "master_id": m1["id"],
        },
    )
    assert busy.status_code == 201, busy.text
    users = client.get("/api/admin/users", headers=admin_headers).json()
    me = next(u for u in users if u["email"] == "master@msb.local")

    cookies = _login(client, "master@msb.local", "master123")
    r = client.post(
        f"/repairs/{busy.json()['id']}/assign",
        cookies=cookies,
        data={"master_ids": str(me["id"]), "next": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 4. Доставка: кнопка отмечает заказ, комментарий необязателен
# ---------------------------------------------------------------------------
def test_intake_without_delivery_is_not_delivery(client, admin_headers):
    cookies = _login(client)
    _intake_form(client, cookies, full_name="Без Доставки", phone="+993 61 100007")
    rep = _find(client, admin_headers, "+993 61 100007")
    assert rep["is_delivery"] is False, "каждый заказ считался привезённым"
    assert rep["delivery_district"] is None
    assert rep["delivery_comment"] is None


def test_intake_delivery_saves_district_and_comment(client, admin_headers):
    cookies = _login(client)
    _intake_form(
        client, cookies,
        full_name="С Доставкой", phone="+993 61 100008",
        is_delivery="1", delivery_district="Парахат 3/2",
        delivery_comment="позвонить за час",
    )
    rep = _find(client, admin_headers, "+993 61 100008")
    assert rep["is_delivery"] is True
    assert rep["delivery_district"] == "Парахат 3/2"
    assert rep["delivery_comment"] == "позвонить за час"

    # Комментарий необязательный — без него доставка всё равно сохраняется.
    _intake_form(
        client, cookies,
        full_name="Доставка Без Комментария", phone="+993 61 100009",
        is_delivery="1", delivery_district="Мир 4",
    )
    rep = _find(client, admin_headers, "+993 61 100009")
    assert rep["is_delivery"] is True
    assert rep["delivery_district"] == "Мир 4"
    assert rep["delivery_comment"] is None

    # В окне приёмки есть поле комментария.
    page = client.get("/repairs/new?type=Телевизоры", cookies=cookies)
    assert 'name="delivery_comment"' in page.text
    assert "data-delivery-comment" in page.text


# ---------------------------------------------------------------------------
# 5–6. Список: колонка «Что починили», без вкладок/заголовка/подсказки
# ---------------------------------------------------------------------------
def test_list_has_work_done_column(client, admin_headers, operator_headers, city_id):
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "workdone-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Колонка Клиент", "phone": "+993 61 100010", "consent_pdn": True},
            "device_type": "Телевизоры",
            "brand": "Sony",
            "fault_client": "нет изображения",
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    upd = client.patch(
        f"/api/repairs/{rid}", headers=admin_headers,
        json={"work_done": "замена подсветки, прошивка"},
    )
    assert upd.status_code == 200, upd.text

    cookies = _login(client)
    page = client.get("/repairs?q=Колонка Клиент", cookies=cookies)
    assert page.status_code == 200
    assert "Что починили" in page.text
    assert "замена подсветки, прошивка" in page.text


def test_list_has_no_stage_tabs_title_and_dblclick_hint(client):
    cookies = _login(client)
    page = client.get("/repairs", cookies=cookies)
    assert page.status_code == 200
    html = page.text
    # Быстрые фильтры-этапы и заголовок «Все ремонты / Реестр по этапам» убраны.
    assert 'class="tabs"' not in html
    assert "Реестр по этапам" not in html
    assert "<h1>Все ремонты</h1>" not in html
    # Подсказки про двойной клик больше нет.
    assert "Двойной клик по ячейке" not in html
    assert "rlist-edit-hint" not in html
    # Поиск и размер страницы остались.
    assert 'name="per_page"' in html
    assert 'name="q"' in html


# ---------------------------------------------------------------------------
# 7. Пять статусов + подсветка
# ---------------------------------------------------------------------------
def test_only_five_statuses_are_available(client, admin_headers):
    r = client.get("/api/admin/settings/repair_statuses", headers=admin_headers)
    if r.status_code == 200:
        items = r.json().get("value", {}).get("items") or r.json().get("items")
        assert items == list(DEFAULT_REPAIR_STATUSES)
    assert DEFAULT_REPAIR_STATUSES == [
        "Новый", "На диагностике", "В работе", "Ждёт запчастей", "Завершён",
    ]


def test_list_highlights_unpaid_issued_and_ready_in_service(
    client, admin_headers, operator_headers, city_id
):
    # 1) Завершён, но техника ещё в сервисе → строка «is-ready».
    ready = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "hl-ready-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Готов Стоит", "phone": "+993 61 100011", "consent_pdn": True},
            "device_type": "Телевизоры",
            "fault_client": "не включается",
        },
    ).json()
    client.post(f"/api/repairs/{ready['id']}/finish", headers=operator_headers)

    # 2) Технику выдали, а ремонта не оплатили → строка «is-unpaid».
    unpaid = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "hl-unpaid-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Забрал Не Платит", "phone": "+993 61 100012", "consent_pdn": True},
            "device_type": "Телевизоры",
            "fault_client": "нет звука",
        },
    ).json()
    client.post(f"/api/repairs/{unpaid['id']}/finish", headers=operator_headers)
    issued = client.post(f"/api/repairs/{unpaid['id']}/issue", headers=operator_headers)
    assert issued.status_code == 200, issued.text
    assert issued.json()["issued_at"] is not None

    cookies = _login(client)
    page = client.get(
        "/repairs?q=Забрал Не Платит", cookies=cookies
    ).text
    assert _row_class(page) == "is-unpaid"
    assert "выдано, не оплачено" in page

    page = client.get("/repairs?q=Готов Стоит", cookies=cookies).text
    assert _row_class(page) == "is-ready"
    # Подсветка «готово, но в сервисе» включается кнопкой.
    assert "Готово, но в сервисе" in page
    assert "hl=ready" in page

    highlighted = client.get("/repairs?q=Готов Стоит&hl=ready", cookies=cookies).text
    assert "is-hl-ready" in highlighted


def test_legacy_statuses_are_migrated_to_new_five():
    """Миграция данных приводит старые статусы к новым пяти."""
    from app.db.datamigrate import migrate_repair_statuses
    from app.db.models import RepairStatus

    async def _go(db):
        row = (await db.execute(select(Repair).limit(1))).scalars().first()
        if row is None:
            return None
        row.status = "Не забрано"
        await db.flush()
        repair_id = row.id
        info = await migrate_repair_statuses(db)
        await db.commit()
        after = (
            await db.execute(select(Repair).where(Repair.id == repair_id))
        ).scalar_one()
        return info, after.status

    result = _run(_go)
    assert result is not None, "в тестовой БД нет ни одного ремонта"
    info, status = result
    assert status == RepairStatus.DONE
    assert info["statuses"] == list(RepairStatus.ALL)
    assert info["renamed"] >= 1


def test_issue_marks_repair_and_stops_being_in_service(
    client, operator_headers, admin_headers, city_id
):
    rep = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "issue-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Выдача Клиент", "phone": "+993 61 100013", "consent_pdn": True},
            "device_type": "Телевизоры",
            "fault_client": "не включается",
        },
    ).json()
    client.post(f"/api/repairs/{rep['id']}/finish", headers=operator_headers)

    cookies = _login(client)
    before = client.get("/repairs?q=Выдача Клиент", cookies=cookies).text
    assert _row_class(before) == "is-ready"

    r = client.post(
        f"/repairs/{rep['id']}/issue", cookies=cookies,
        data={"next": "/repairs"}, follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    after = client.get("/repairs?q=Выдача Клиент", cookies=cookies).text
    # Технику забрали → «в сервисе» больше не светится, зато светится долг.
    assert _row_class(after) == "is-unpaid"


def test_issue_forbidden_for_master(client, operator_headers, city_id):
    rep = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "issue-2"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Выдача Мастер", "phone": "+993 61 100014", "consent_pdn": True},
            "device_type": "Телевизоры",
            "fault_client": "не включается",
        },
    ).json()
    cookies = _login(client, "master@msb.local", "master123")
    r = client.post(
        f"/repairs/{rep['id']}/issue", cookies=cookies,
        data={"next": "/repairs"}, follow_redirects=False,
    )
    assert r.status_code == 403, r.text
