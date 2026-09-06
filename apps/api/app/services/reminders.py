"""Ежедневные SMS-напоминания «заберите технику».

Сценарий: мастер/оператор нажал «Ремонт закончен» → клиент получил SMS о
готовности → но технику не забрал. Дальше раз в сутки (пока ремонт в статусе
«Готово к выдаче» или «Не забрано») клиенту уходит напоминание с названием
сервиса и адресом. Как только технику выдали («Выдано», «Архив», «Отказ») —
напоминания прекращаются.

Текст — шаблон `pickup_reminder` из «Админ → SMS» (см. `services/sms.py`).
Расписание задаётся переменными окружения `REMINDER_*` (см. `core/config.py`).

Запуск — фоновая задача в `main.py` (`reminder_loop`), она просыпается каждые
`REMINDER_CHECK_INTERVAL_MIN` минут и вызывает `send_due_reminders`. Тот же
проход можно запустить вручную: `POST /api/admin/reminders/run` (только admin).

Напоминание отправляется КАЖДЫЙ РОВНО ОДИН РАЗ: перед отправкой строка ремонта
«заявляется» условным UPDATE (`WHERE reminder_next_at = <прежнее значение>`).
Если API запущено в несколько воркеров, второй воркер увидит rowcount = 0 и
пропустит ремонт — дубль клиенту не придёт.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.base import utcnow
from app.db.models import Repair, RepairEvent
from app.services.sms import send_pickup_reminder_sms, sms_enabled

logger = logging.getLogger("msb.reminders")

# В каких статусах клиенту напоминают забрать технику.
REMINDER_STATUSES = ("Готово к выдаче", "Не забрано")
# В каких статусах напоминания прекращаются (технику забрали/списали).
STOP_STATUSES = ("Выдано", "Архив", "Отказ")

# Сколько ремонтов обрабатываем за один проход (защита от «шторма» после
# простоя: остальные дойдут в следующий проход через несколько минут).
BATCH_LIMIT = 200

# Через сколько времени повторить попытку, если шлюз SMS не ответил.
RETRY_HOURS = 1


# ---------------------------------------------------------------------------
# Планирование (вызывается из routers/repairs.py)
# ---------------------------------------------------------------------------
def schedule_reminders(repair: Repair, now: datetime | None = None) -> bool:
    """Поставить ремонт в очередь напоминаний.

    Первое напоминание — через `REMINDER_FIRST_DELAY_HOURS` после готовности
    (в тот же день клиент уже получил SMS «ремонт готов»). Возвращает True,
    если план действительно поставлен/изменён.
    """
    now = now or utcnow()
    if repair.status not in REMINDER_STATUSES:
        return False
    if repair.reminder_next_at is not None:
        return False  # уже запланировано — не сбрасываем отсчёт
    repair.reminder_next_at = now + timedelta(hours=settings.REMINDER_FIRST_DELAY_HOURS)
    repair.reminder_count = 0
    return True


def cancel_reminders(repair: Repair) -> bool:
    """Снять ремонт с напоминаний (технику забрали / ремонт закрыт)."""
    if repair.reminder_next_at is None:
        return False
    repair.reminder_next_at = None
    return True


# ---------------------------------------------------------------------------
# Время отправки
# ---------------------------------------------------------------------------
def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.REMINDER_TIMEZONE)
    except Exception:  # noqa: BLE001 — неизвестная зона в env не должна ронять задачу
        logger.warning("REMINDER_TIMEZONE=%s неизвестна, беру UTC", settings.REMINDER_TIMEZONE)
        return ZoneInfo("UTC")


def local_now(now: datetime | None = None) -> datetime:
    """Локальное время сервиса (Ашхабад) из naive-UTC, который лежит в БД."""
    now = now or utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(_tz())


def in_sending_window(now: datetime | None = None) -> bool:
    """Не будим клиента ночью: шлём только в разрешённые местные часы."""
    hour = local_now(now).hour
    lo, hi = settings.REMINDER_SEND_FROM_HOUR, settings.REMINDER_SEND_TO_HOUR
    if lo == hi:
        return True
    if lo < hi:
        return lo <= hour < hi
    # Окно через полночь (например, с 22 до 6).
    return hour >= lo or hour < hi


def days_waiting(repair: Repair, now: datetime | None = None) -> int | None:
    """Сколько полных суток техника ждёт клиента после «Ремонт закончен»."""
    if not repair.ready_at:
        return None
    now = now or utcnow()
    return max(0, (now - repair.ready_at).days)


# ---------------------------------------------------------------------------
# Основной проход
# ---------------------------------------------------------------------------
async def send_due_reminders(db: AsyncSession, now: datetime | None = None) -> dict:
    """Отправить все подошедшие напоминания. Не бросает исключений наружу."""
    now = now or utcnow()
    report = {
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "due": 0,
        "reason": None,
        "checked_at": now.isoformat(),
    }

    if not settings.REMINDER_ENABLED:
        report["reason"] = "reminder_disabled"
        return report
    if not await sms_enabled(db):
        # Шлюз выключен/не настроен: ничего не отправляем и НЕ сдвигаем даты,
        # чтобы после включения напоминания ушли, а не «сгорели».
        report["reason"] = "sms_disabled"
        return report
    if not in_sending_window(now):
        report["reason"] = "quiet_hours"
        return report

    rows = await db.execute(
        select(Repair)
        # events нужны для selectinload: запись о напоминании добавляется в
        # repair.events, а ленивая подгрузка в async-сессии невозможна.
        .options(selectinload(Repair.client), selectinload(Repair.events))
        .where(
            Repair.reminder_next_at.isnot(None),
            Repair.reminder_next_at <= now,
            Repair.status.in_(REMINDER_STATUSES),
        )
        .order_by(Repair.reminder_next_at)
        .limit(BATCH_LIMIT)
    )
    repairs = list(rows.scalars().all())
    report["due"] = len(repairs)

    for repair in repairs:
        try:
            outcome = await _send_one(db, repair, now)
        except Exception as exc:  # noqa: BLE001 — один ремонт не роняет весь проход
            logger.exception("Reminder failed for repair %s", repair.id)
            await db.rollback()
            outcome = "failed"
            report.setdefault("errors", []).append(f"{repair.number}: {exc}")
        report[outcome] = report.get(outcome, 0) + 1

    return report


async def _send_one(db: AsyncSession, repair: Repair, now: datetime) -> str:
    """Отправить одно напоминание. Возвращает 'sent' | 'failed' | 'skipped'."""
    # Лимит напоминаний (0 = без лимита, напоминаем, пока не заберут).
    limit = settings.REMINDER_MAX_COUNT
    if limit and (repair.reminder_count or 0) >= limit:
        repair.reminder_next_at = None
        await db.commit()
        return "skipped"

    waiting = days_waiting(repair, now)
    previous_next_at = repair.reminder_next_at
    next_number = (repair.reminder_count or 0) + 1
    every = timedelta(hours=settings.REMINDER_EVERY_HOURS)

    # Заявка на напоминание: условный UPDATE защищает от двойной отправки,
    # если задачу одновременно выполняют несколько воркеров.
    claimed = await db.execute(
        update(Repair)
        .where(Repair.id == repair.id, Repair.reminder_next_at == previous_next_at)
        .values(
            reminder_next_at=now + every,
            reminder_last_at=now,
            reminder_count=next_number,
        )
    )
    if claimed.rowcount != 1:
        await db.rollback()
        return "skipped"
    await db.commit()

    # expire_on_commit=False, поэтому client/поля доступны и после commit.
    repair.reminder_next_at = now + every
    repair.reminder_last_at = now
    repair.reminder_count = next_number

    result = await send_pickup_reminder_sms(repair, db=db)
    # Пересобираем текст с числом суток ожидания (для истории ремонта).
    if result.get("ok"):
        repair.events.append(
            RepairEvent(
                repair_id=repair.id,
                type="notify",
                actor_id=None,
                data={
                    "message": (
                        f"Клиенту отправлено напоминание забрать технику "
                        f"(№{next_number}, ждёт {waiting} дн.)"
                        if waiting is not None
                        else f"Клиенту отправлено напоминание забрать технику (№{next_number})"
                    ),
                    "kind": "pickup_reminder",
                    "sms_text": result.get("text"),
                    "phone": repair.client.phone if repair.client else None,
                },
            )
        )
        await db.commit()
        return "sent"

    # Шлюз не ответил: возвращаем напоминание в очередь через час и не считаем
    # его отправленным (иначе клиент остался бы без напоминания на сутки).
    detail = result.get("detail", "ошибка шлюза")
    retry_at = now + timedelta(hours=RETRY_HOURS)
    await db.execute(
        update(Repair)
        .where(Repair.id == repair.id)
        .values(reminder_next_at=retry_at, reminder_count=next_number - 1)
    )
    repair.reminder_next_at = retry_at
    repair.reminder_count = next_number - 1
    repair.events.append(
        RepairEvent(
            repair_id=repair.id,
            type="notify",
            actor_id=None,
            data={
                "message": f"Напоминание клиенту не отправлено: {detail}",
                "kind": "pickup_reminder_failed",
                "detail": detail,
            },
        )
    )
    await db.commit()
    logger.warning("Pickup reminder for %s failed: %s", repair.number, detail)
    return "failed"


async def reminder_loop(stop: asyncio.Event) -> None:
    """Фоновый цикл: каждые N минут проходим по очереди напоминаний."""
    from app.db.session import async_session_factory

    interval = max(1, settings.REMINDER_CHECK_INTERVAL_MIN) * 60
    logger.info(
        "Pickup-reminder loop started (every %s мин, статусы: %s)",
        settings.REMINDER_CHECK_INTERVAL_MIN,
        ", ".join(REMINDER_STATUSES),
    )
    while not stop.is_set():
        try:
            async with async_session_factory() as db:
                report = await send_due_reminders(db)
            if report.get("sent") or report.get("failed"):
                logger.info("Pickup reminders: %s", report)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен умирать
            logger.exception("Pickup-reminder loop error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    logger.info("Pickup-reminder loop stopped")
