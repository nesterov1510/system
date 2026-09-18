"""Две очереди CUPS на сервере MSB: `office_printer_a4` и `3B-350B`.

Оба принтера подключены к CUPS той же машины, где работают API и print-agent:
бланки A4 печатаются в `office_printer_a4`, этикетки 58×38 — в `3B-350B`.
Проверяем, что режим `cups_local` доступен и для бланков (раньше у A4-принтера
были только agent/ipp), что задания не перепутаны между очередями и что
устаревшие настройки (Epson L3250 через драйвер ОС, этикетки через удалённый
CUPS) приводятся к локальным очередям при старте.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import delete

from app.db.models import Setting
from app.db.session import async_session_factory
from app.services.settings import get_label_printer, get_printer

A4_QUEUE = "office_printer_a4"
LABEL_QUEUE = "3B-350B"


def _run(coro):
    return asyncio.run(coro)


async def _read_settings():
    async with async_session_factory() as db:
        return await get_printer(db), await get_label_printer(db)


async def _drop_setting(key: str):
    async with async_session_factory() as db:
        await db.execute(delete(Setting).where(Setting.key == key))
        await db.commit()


@pytest.fixture(autouse=True)
def _clear_web_session(client):
    """Сессионный TestClient общий: не оставляем cookie логина соседним тестам."""
    yield
    client.get("/logout", follow_redirects=False)
    client.cookies.clear()


@pytest.fixture(autouse=True)
def _restore_printer_settings(client, admin_headers):
    """Настройки печати общие для всей сессии тестов — возвращаем как было."""
    before = client.get("/api/admin/printer", headers=admin_headers).json()
    yield
    for endpoint, key in (
        ("/api/admin/printer", "printer"),
        ("/api/admin/printer/label", "label_printer"),
    ):
        value = before.get(key) or {}
        if key == "printer":
            body = {k: value.get(k, "") for k in ("ip", "port", "mode", "name")}
        else:
            body = {
                k: value.get(k, "")
                for k in ("ip", "port", "mode", "name", "media")
            }
        if not body.get("name"):
            continue
        restored = client.put(endpoint, headers=admin_headers, json=body)
        assert restored.status_code == 200, restored.text


def _configure(client, admin_headers):
    a4 = client.put(
        "/api/admin/printer",
        headers=admin_headers,
        json={"mode": "cups_local", "name": A4_QUEUE},
    )
    assert a4.status_code == 200, a4.text
    label = client.put(
        "/api/admin/printer/label",
        headers=admin_headers,
        json={"mode": "cups_local", "name": LABEL_QUEUE, "media": "Custom.58x38mm"},
    )
    assert label.status_code == 200, label.text


def test_defaults_point_at_server_queues():
    """Без сохранённых настроек — очереди CUPS самого сервера, режим локальный."""
    _run(_drop_setting("printer"))
    _run(_drop_setting("label_printer"))

    printer, label = _run(_read_settings())

    assert printer["mode"] == "cups_local"
    assert printer["name"] == A4_QUEUE
    assert label["mode"] == "cups_local"
    assert label["name"] == LABEL_QUEUE
    # Локальной очереди адрес не нужен: его знает CUPS.
    assert printer["ip"] == "" and label["ip"] == ""


def test_local_a4_queue_saved_without_ip(client, admin_headers):
    r = client.put(
        "/api/admin/printer",
        headers=admin_headers,
        json={"mode": "cups_local", "name": A4_QUEUE, "ip": "", "port": 631},
    )
    assert r.status_code == 200, r.text
    saved = r.json()["printer"]
    assert saved == {"ip": "", "port": 631, "mode": "cups_local", "name": A4_QUEUE}

    config = client.get("/api/admin/printer", headers=admin_headers).json()
    assert config["printer"]["name"] == A4_QUEUE
    assert config["printer"]["mode"] == "cups_local"


@pytest.mark.parametrize(
    "body,status",
    [
        ({"mode": "cups_local"}, 400),  # без имени очереди
        ({"mode": "windows_spool"}, 400),  # неизвестный режим
        ({"mode": "cups_remote", "name": A4_QUEUE}, 400),  # удалённый CUPS без IP
        ({"mode": "ipp", "name": A4_QUEUE}, 400),  # IPP без IP
        ({"mode": "ipp", "name": A4_QUEUE, "ip": "192.168.5.40"}, 200),
    ],
)
def test_a4_printer_validation(client, admin_headers, body, status):
    r = client.put("/api/admin/printer", headers=admin_headers, json=body)
    assert r.status_code == status, r.text


def test_label_test_print_works_without_ip(client, admin_headers):
    """Локальной очереди этикеток адрес не нужен — тестовая печать возможна."""
    r = client.put(
        "/api/admin/printer/label",
        headers=admin_headers,
        json={"mode": "cups_local", "name": LABEL_QUEUE, "media": "Custom.58x38mm"},
    )
    assert r.status_code == 200, r.text

    test_print = client.post("/api/admin/printer/label/test", headers=admin_headers)
    assert test_print.status_code == 200, test_print.text
    assert test_print.json()["status"] == "queued"


def test_blank_and_label_go_to_their_own_queues(
    client, admin_headers, operator_headers, city_id
):
    """Бланк — в office_printer_a4, этикетка — в 3B-350B. Не наоборот."""
    _configure(client, admin_headers)

    created = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": f"queues-{uuid.uuid4().hex[:8]}"},
        json={
            "city_id": city_id,
            "client": {
                "full_name": "Очередь Тест",
                "phone": f"+993 65 {uuid.uuid4().int % 100000:05d}",
                "consent_pdn": True,
                "consent_storage": True,
            },
            "device_type": "ТВ",
            "brand": "LG",
            "model": "43UR",
            "fault_client": "нет звука",
        },
    )
    assert created.status_code == 201, created.text
    repair_id = created.json()["id"]

    blank = client.post(f"/api/repairs/{repair_id}/print", headers=admin_headers)
    assert blank.status_code == 200, blank.text
    label = client.post(f"/api/repairs/{repair_id}/print-label", headers=admin_headers)
    assert label.status_code == 200, label.text

    jobs = client.get("/api/print/jobs", headers=admin_headers).json()
    mine = [j for j in jobs if j.get("repair_id") == repair_id]
    blank_job = next(j for j in mine if j["template_id"] == "default")
    label_job = next(j for j in mine if j["template_id"] == "repair-label-58x38")

    assert blank_job["payload"]["printer"]["name"] == A4_QUEUE
    assert blank_job["payload"]["printer"]["mode"] == "cups_local"
    assert label_job["payload"]["printer"]["name"] == LABEL_QUEUE
    assert label_job["payload"]["printer"]["mode"] == "cups_local"
    assert label_job["payload"]["printer"]["media"] == "Custom.58x38mm"


def _login_webui(client):
    r = client.post(
        "/login",
        data={"email": "admin@msb.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def test_webui_saves_both_local_queues(client, admin_headers):
    _configure(client, admin_headers)
    _login_webui(client)

    page = client.get("/admin/settings?section=printer")
    assert page.status_code == 200, page.text
    assert A4_QUEUE in page.text
    assert LABEL_QUEUE in page.text
    assert 'value="cups_local" selected' in page.text

    # Форма бланков: локальная очередь сохраняется без IP.
    r = client.post(
        "/admin/settings/printer",
        data={"printer_mode": "cups_local", "printer_name": A4_QUEUE, "printer_port": "631"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    empty = client.post(
        "/admin/settings/printer",
        data={"printer_mode": "cups_local", "printer_name": ""},
        follow_redirects=False,
    )
    assert empty.status_code == 400, empty.text
    assert "имя очереди" in empty.text.lower()

    unknown = client.post(
        "/admin/settings/printer",
        data={"printer_mode": "bluetooth", "printer_name": A4_QUEUE},
        follow_redirects=False,
    )
    assert unknown.status_code == 400, unknown.text


def test_migration_moves_legacy_settings_to_local_queues(client, admin_headers):
    """Epson L3250 (agent) и 3B-350B через удалённый CUPS → локальные очереди."""
    from app.db.datamigrate import MIGRATIONS, align_cups_queues
    from app.services.settings import set_setting

    # Миграция должна быть в реестре, иначе при старте она не выполнится.
    assert MIGRATIONS["cups_local_queues_v1"] is align_cups_queues

    async def _arrange():
        async with async_session_factory() as db:
            await set_setting(
                db, "printer",
                {"ip": "", "port": 631, "mode": "agent", "name": "Epson L3250"},
            )
            await set_setting(
                db, "label_printer",
                {
                    "ip": "192.168.5.238", "port": 631, "mode": "cups_remote",
                    "name": "3B-350B", "width_mm": 58, "height_mm": 38,
                    "media": "Custom.58x38mm",
                },
            )

    async def _migrate():
        async with async_session_factory() as db:
            return await align_cups_queues(db)

    _run(_arrange())
    changed = _run(_migrate())
    assert "printer" in changed and "label_printer" in changed, changed

    printer, label = _run(_read_settings())
    assert printer == {"ip": "", "port": 631, "mode": "cups_local", "name": A4_QUEUE}
    assert label["mode"] == "cups_local"
    assert label["name"] == LABEL_QUEUE
    assert label["ip"] == ""
    assert label["media"] == "Custom.58x38mm"

    # Повторный запуск ничего не меняет (миграция идемпотентна).
    assert _run(_migrate()) == {"ok": True}


def test_migration_keeps_deliberate_settings(client, admin_headers):
    """Чужую конфигурацию (ipp, своя очередь) миграция не переписывает."""
    from app.db.datamigrate import align_cups_queues
    from app.services.settings import set_setting

    async def _arrange():
        async with async_session_factory() as db:
            await set_setting(
                db, "printer",
                {"ip": "192.168.5.40", "port": 631, "mode": "ipp", "name": "office_printer_a4"},
            )
            await set_setting(
                db, "label_printer",
                {
                    "ip": "192.168.5.99", "port": 631, "mode": "cups_remote",
                    "name": "Zebra_58", "width_mm": 58, "height_mm": 38, "media": "",
                },
            )

    async def _migrate():
        async with async_session_factory() as db:
            return await align_cups_queues(db)

    _run(_arrange())
    assert _run(_migrate()) == {"ok": True}

    printer, label = _run(_read_settings())
    assert printer["mode"] == "ipp"
    assert label["name"] == "Zebra_58"
    assert label["mode"] == "cups_remote"
