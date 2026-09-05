"""Ежедневные SMS-напоминания клиенту «заберите технику».

Проверяем весь сценарий:
  «Ремонт закончен» → напоминание запланировано на завтра → фоновый проход
  отправляет SMS (текст по шаблону с названием сервиса и адресом) → дата
  сдвигается на сутки → после выдачи напоминания прекращаются.

Отдельно — защита от «шума»: не шлём ночью, не шлём при выключенном шлюзе
(и не сжигаем при этом напоминание), при ошибке шлюза повторяем через час,
двойной проход не отправляет два одинаковых SMS.
"""
import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.db.base import utcnow
from app.db.models import Repair, RepairEvent
from app.db.session import async_session_factory
from app.services import reminders as rem
from app.services.sms import (
    DEFAULT_PICKUP_REMINDER_TEXT,
    build_pickup_reminder_sms,
    pickup_reminder_tokens,
)

# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _run(fn):
    """Выполнить асинхронную функцию с сессией БД (тесты синхронные)."""

    async def _wrap():
        async with async_session_factory() as db:
            return await fn(db)

    return asyncio.run(_wrap())


def _mk_repair(client, headers, city_id, key, name="Клиент Напоминание", phone="+993 61 555000"):
    r = client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": city_id,
            "client": {"full_name": name, "phone": phone, "consent_pdn": True},
            "device_type": "Телевизоры",
            "brand": "Samsung",
            "model": "UE55",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _patch_repair(repair_id, **values):
    """Прямо в БД: подвинуть дату напоминания / счётчик (имитация времени)."""

    async def _go(db):
        await db.execute(
            update(Repair).where(Repair.id == uuid.UUID(repair_id)).values(**values)
        )
        await db.commit()

    _run(_go)


def _load_repair(repair_id):
    async def _go(db):
        row = await db.execute(select(Repair).where(Repair.id == uuid.UUID(repair_id)))
        return row.scalar_one()

    return _run(_go)


def _only_this_reminder(repair_id):
    """Снять с очереди все напоминания, кроме нужного ремонта.

    Тесты идут по общей (сессионной) БД, а часть сценариев намеренно оставляет
    напоминание просроченным («тихие часы», «шлюз выключен»). Без очистки
    следующий проход видел бы чужие ремонты и счётчики sent/failed «плыли» бы.
    """

    async def _go(db):
        await db.execute(
            update(Repair)
            .where(
                Repair.reminder_next_at.isnot(None),
                Repair.id != uuid.UUID(repair_id),
            )
            .values(reminder_next_at=None)
        )
        await db.commit()

    _run(_go)


def _open_window(monkeypatch):
    """Круглосуточное окно отправки — чтобы тест не зависел от часа запуска."""
    monkeypatch.setattr(settings, "REMINDER_SEND_FROM_HOUR", 0)
    monkeypatch.setattr(settings, "REMINDER_SEND_TO_HOUR", 24)


def _closed_window(monkeypatch):
    """Тихие часы: окно на 2 часа вперёд от текущего местного."""
    hour = rem.local_now().hour
    monkeypatch.setattr(settings, "REMINDER_SEND_FROM_HOUR", (hour + 1) % 24)
    monkeypatch.setattr(settings, "REMINDER_SEND_TO_HOUR", (hour + 2) % 24)


def _fake_gateway(monkeypatch, ok=True, detail="http_200"):
    """Подменить отправку SMS: ловим текст/телефон, сеть не дёргаем."""
    sent = []

    async def _fake_send(repair, db=None):
        text = build_pickup_reminder_sms(repair)
        sent.append(
            {
                "phone": repair.client.phone if repair.client else None,
                "text": text,
                "number": repair.number,
            }
        )
        return {"ok": ok, "detail": detail, "text": text}

    async def _enabled(db=None):
        return True

    monkeypatch.setattr(rem, "send_pickup_reminder_sms", _fake_send)
    monkeypatch.setattr(rem, "sms_enabled", _enabled)
    return sent


# ---------------------------------------------------------------------------
# Шаблон текста
# ---------------------------------------------------------------------------


def test_default_reminder_text_has_service_and_address():
    """Стандартный шаблон — тот, что просил сервис: название + адрес."""
    assert "MERYOSAB" in DEFAULT_PICKUP_REMINDER_TEXT
    assert "Парахат 3/2" in DEFAULT_PICKUP_REMINDER_TEXT
    assert "забрать" in DEFAULT_PICKUP_REMINDER_TEXT.lower()


def test_build_reminder_text_uses_default_template():
    class _Client:
        full_name = "Анна"
        phone = "+99361000001"

    class _Repair:
        number = "TV-ASG-2026-00007"
        device_type = "Телевизоры"
        brand = "Samsung"
        model = "UE55"
        client = _Client()
        ready_at = None

    text = build_pickup_reminder_sms(_Repair(), days_waiting=2)
    assert text == DEFAULT_PICKUP_REMINDER_TEXT
    # Плейсхолдеры доступны админу, если он захочет их добавить.
    tokens = pickup_reminder_tokens(_Repair(), days_waiting=2)
    assert tokens["number"] == "TV-ASG-2026-00007"
    assert tokens["device"] == "Телевизоры Samsung UE55"
    assert tokens["days"] == "2"


def test_build_reminder_text_custom_template_with_placeholders():
    class _Client:
        full_name = "Анна"
        phone = "+99361000001"

    class _Repair:
        number = "TV-ASG-2026-00008"
        device_type = "Телевизоры"
        brand = "LG"
        model = None
        client = _Client()
        ready_at = None

    tpl = "{client_name}, ваш {device} (№ {number}) ждёт вас уже {days} дн."
    text = build_pickup_reminder_sms(_Repair(), template=tpl, days_waiting=3)
    assert text == "Анна, ваш Телевизоры LG (№ TV-ASG-2026-00008) ждёт вас уже 3 дн."


def test_unknown_placeholder_does_not_break_text():
    class _Repair:
        number = "X"
        device_type = "ТВ"
        brand = None
        model = None
        client = None
        ready_at = None

    # Опечатка админа в шаблоне не должна ронять отправку.
    assert build_pickup_reminder_sms(_Repair(), template="Забрать {oops}!") == "Забрать !"


# ---------------------------------------------------------------------------
# Планирование
# ---------------------------------------------------------------------------


def test_finish_schedules_reminder_for_next_day(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "rem-finish-1")
    r = client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    assert r.status_code == 200, r.text
    body = r.json()["repair"]

    assert body["status"] == "Готово к выдаче"
    assert body["ready_at"] is not None
    assert body["reminder_next_at"] is not None, "после «Ремонт закончен» напоминание не запланировано"
    assert body["reminder_count"] == 0

    row = _load_repair(body["id"])
    delta = row.reminder_next_at - row.ready_at
    assert timedelta(hours=settings.REMINDER_FIRST_DELAY_HOURS - 1) < delta <= timedelta(
        hours=settings.REMINDER_FIRST_DELAY_HOURS + 1
    )


def test_status_change_to_ready_schedules_reminder(client, operator_headers, city_id):
    """Готовность поставили не кнопкой «Ремонт закончен», а сменой статуса."""
    repair = _mk_repair(client, operator_headers, city_id, "rem-status-1")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"status": "Готово к выдаче"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reminder_next_at"] is not None


def test_issuing_repair_stops_reminders(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "rem-stop-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    assert _load_repair(repair["id"]).reminder_next_at is not None

    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"status": "Выдано"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reminder_next_at"] is None, "после выдачи напоминания должны прекратиться"


def test_not_ready_status_has_no_reminder(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, "rem-notready-1")
    assert repair["reminder_next_at"] is None
    assert repair["reminder_count"] == 0


# ---------------------------------------------------------------------------
# Фоновый проход
# ---------------------------------------------------------------------------


def test_nothing_sent_before_due(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair(client, operator_headers, city_id, "rem-notdue-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    sent = _fake_gateway(monkeypatch)
    _open_window(monkeypatch)

    report = _run(lambda db: rem.send_due_reminders(db))
    assert report["reason"] is None
    assert report["sent"] == 0
    assert sent == []


def test_due_reminder_is_sent_and_rescheduled(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair(client, operator_headers, city_id, "rem-due-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    # «Промотаем» сутки: напоминание просрочено.
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])

    sent = _fake_gateway(monkeypatch)
    _open_window(monkeypatch)

    now = utcnow()
    report = _run(lambda db: rem.send_due_reminders(db, now=now))
    assert report["due"] == 1
    assert report["sent"] == 1, report
    assert report["failed"] == 0

    assert len(sent) == 1
    assert sent[0]["number"] == repair["number"]
    assert sent[0]["phone"] == "+993 61 555000"
    assert "MERYOSAB" in sent[0]["text"]
    assert "Парахат 3/2" in sent[0]["text"]

    row = _load_repair(repair["id"])
    assert row.reminder_count == 1
    assert row.reminder_last_at is not None
    # Следующее напоминание — через сутки, не раньше.
    assert row.reminder_next_at > now + timedelta(hours=settings.REMINDER_EVERY_HOURS - 1)
    assert row.reminder_next_at <= now + timedelta(hours=settings.REMINDER_EVERY_HOURS)


def test_second_pass_does_not_send_twice(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair(client, operator_headers, city_id, "rem-twice-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])
    sent = _fake_gateway(monkeypatch)
    _open_window(monkeypatch)

    first = _run(lambda db: rem.send_due_reminders(db))
    second = _run(lambda db: rem.send_due_reminders(db))
    assert first["sent"] == 1
    assert second["sent"] == 0
    assert len(sent) == 1, "клиенту ушло два одинаковых напоминания"


def test_reminder_written_to_repair_history(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair(client, operator_headers, city_id, "rem-event-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])
    _fake_gateway(monkeypatch)
    _open_window(monkeypatch)
    _run(lambda db: rem.send_due_reminders(db))

    detail = client.get(f"/api/repairs/{repair['id']}", headers=operator_headers).json()
    reminders = [
        e
        for e in detail["events"]
        if e["type"] == "notify" and (e.get("data") or {}).get("kind") == "pickup_reminder"
    ]
    assert len(reminders) == 1
    assert "MERYOSAB" in (reminders[0]["data"].get("sms_text") or "")
    assert detail["reminder_count"] == 1


def test_quiet_hours_do_not_send(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair(client, operator_headers, city_id, "rem-quiet-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    before = _load_repair(repair["id"]).reminder_next_at
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])

    sent = _fake_gateway(monkeypatch)
    _closed_window(monkeypatch)

    report = _run(lambda db: rem.send_due_reminders(db))
    assert report["reason"] == "quiet_hours"
    assert report["sent"] == 0
    assert sent == []
    # Напоминание не «сгорело»: оно уйдёт, как только окно откроется.
    assert _load_repair(repair["id"]).reminder_next_at < utcnow()
    assert before is not None


def test_disabled_gateway_keeps_reminder_queued(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair(client, operator_headers, city_id, "rem-nosms-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])

    async def _disabled(db=None):
        return False

    monkeypatch.setattr(rem, "sms_enabled", _disabled)
    _open_window(monkeypatch)

    report = _run(lambda db: rem.send_due_reminders(db))
    assert report["reason"] == "sms_disabled"
    assert report["sent"] == 0
    row = _load_repair(repair["id"])
    assert row.reminder_count == 0
    assert row.reminder_next_at < utcnow(), "при выключенном шлюзе напоминание должно остаться в очереди"


def test_gateway_failure_retries_sooner_and_does_not_count(
    client, operator_headers, city_id, monkeypatch
):
    repair = _mk_repair(client, operator_headers, city_id, "rem-fail-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])

    _fake_gateway(monkeypatch, ok=False, detail="http_500")
    _open_window(monkeypatch)

    now = utcnow()
    report = _run(lambda db: rem.send_due_reminders(db, now=now))
    assert report["failed"] >= 1, report
    assert report["sent"] == 0

    row = _load_repair(repair["id"])
    assert row.reminder_count == 0, "неудачная попытка не должна считаться отправленной"
    # Повтор через час, а не через сутки.
    assert row.reminder_next_at <= now + timedelta(hours=rem.RETRY_HOURS)
    assert row.reminder_next_at > now


def test_max_count_limit_stops_reminders(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair(client, operator_headers, city_id, "rem-limit-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    _patch_repair(
        repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5), reminder_count=3
    )
    _only_this_reminder(repair["id"])

    sent = _fake_gateway(monkeypatch)
    _open_window(monkeypatch)
    monkeypatch.setattr(settings, "REMINDER_MAX_COUNT", 3)

    report = _run(lambda db: rem.send_due_reminders(db))
    assert report["sent"] == 0
    assert report["skipped"] == 1
    assert sent == []
    assert _load_repair(repair["id"]).reminder_next_at is None


def test_disabled_feature_sends_nothing(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair(client, operator_headers, city_id, "rem-off-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])
    sent = _fake_gateway(monkeypatch)
    _open_window(monkeypatch)
    monkeypatch.setattr(settings, "REMINDER_ENABLED", False)

    report = _run(lambda db: rem.send_due_reminders(db))
    assert report["reason"] == "reminder_disabled"
    assert sent == []


def test_template_from_admin_is_used(client, admin_headers, operator_headers, city_id, monkeypatch):
    """Текст напоминания правится в «Админ → SMS» и применяется без перезапуска."""
    custom = "Заберите {device} (№ {number}) — MERYOSAB, Парахат 3/2 ж14."
    r = client.put(
        "/api/admin/sms/templates",
        headers=admin_headers,
        json={"pickup_reminder": custom},
    )
    assert r.status_code == 200, r.text
    assert r.json()["templates"]["pickup_reminder"] == custom

    cfg = client.get("/api/admin/sms", headers=admin_headers).json()
    assert cfg["templates"]["pickup_reminder"] == custom
    assert "days" in cfg["template_fields"]["pickup_reminder"]

    repair = _mk_repair(client, operator_headers, city_id, "rem-tpl-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])

    # Здесь уже НЕ подменяем отправку текста: пусть сервис сам возьмёт шаблон
    # из настроек. Ловим только факт отправки.
    captured = []

    async def _enabled(db=None):
        return True

    from app.services import sms as sms_module

    async def _fake_send(phone, text, db=None):
        captured.append({"phone": phone, "text": text})
        return {"ok": True, "detail": "http_200"}

    monkeypatch.setattr(rem, "sms_enabled", _enabled)
    monkeypatch.setattr(sms_module, "send_sms", _fake_send)
    _open_window(monkeypatch)

    report = _run(lambda db: rem.send_due_reminders(db))
    assert report["sent"] >= 1, report
    mine = [c for c in captured if repair["number"] in c["text"]]
    assert len(mine) == 1, captured
    assert (
        mine[0]["text"]
        == f"Заберите Телевизоры Samsung UE55 (№ {repair['number']}) — MERYOSAB, Парахат 3/2 ж14."
    )

    # Возвращаем шаблон по умолчанию, чтобы не влиять на другие тесты.
    client.put(
        "/api/admin/sms/templates",
        headers=admin_headers,
        json={"pickup_reminder": ""},
    )


# ---------------------------------------------------------------------------
# Админка: очередь и ручной запуск
# ---------------------------------------------------------------------------


def test_admin_reminders_queue_shows_scheduled_repairs(
    client, admin_headers, operator_headers, city_id
):
    repair = _mk_repair(client, operator_headers, city_id, "rem-queue-1")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)

    r = client.get("/api/admin/reminders", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schedule"]["every_hours"] == settings.REMINDER_EVERY_HOURS
    numbers = [i["number"] for i in body["items"]]
    assert repair["number"] in numbers
    item = next(i for i in body["items"] if i["number"] == repair["number"])
    assert item["next_at"] is not None
    assert item["sent_count"] == 0


def test_admin_run_reminders_endpoint(client, admin_headers, operator_headers, monkeypatch):
    _fake_gateway(monkeypatch)
    _open_window(monkeypatch)

    r = client.post("/api/admin/reminders/run", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"sent", "failed", "skipped", "due"} <= set(body)

    # Оператору ручной запуск рассылки недоступен (роутер — только admin).
    assert client.post("/api/admin/reminders/run", headers=operator_headers).status_code == 403


def test_events_for_reminders_are_recorded_once(client, operator_headers, city_id, monkeypatch):
    """Два прохода подряд = одно напоминание и одно событие в истории."""
    repair = _mk_repair(client, operator_headers, city_id, "rem-events-2")
    client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    _patch_repair(repair["id"], reminder_next_at=utcnow() - timedelta(minutes=5))
    _only_this_reminder(repair["id"])
    _fake_gateway(monkeypatch)
    _open_window(monkeypatch)

    _run(lambda db: rem.send_due_reminders(db))
    _run(lambda db: rem.send_due_reminders(db))

    async def _count(db):
        rows = await db.execute(
            select(RepairEvent).where(
                RepairEvent.repair_id == uuid.UUID(repair["id"]),
                RepairEvent.type == "notify",
            )
        )
        return [e for e in rows.scalars().all() if (e.data or {}).get("kind") == "pickup_reminder"]

    assert len(_run(_count)) == 1
