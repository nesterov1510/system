"""Одноразовые миграции ДАННЫХ (в отличие от `db/migrate.py` — про колонки).

`Base.metadata.create_all` создаёт таблицы, `db/migrate.py` добавляет колонки,
но ни то, ни другое не умеет пересчитать уже лежащие в БД значения. Здесь —
список идемпотентных пересчётов, каждый помечается применённым в
`Setting["data_migrations"]`, поэтому при следующем старте не повторяется.

`client_phone_norm_v2`: старая `normalize_phone()` была написана под российские
коды 7/8 и не приводила туркменские номера к единому виду, из-за чего один
человек, записанный как «+993 61 234567» и как «8 61 234567», получал две
разные записи в `clients`.

`cups_local_queues_v1`: оба принтера стоят в CUPS самого сервера MSB —
`office_printer_a4` (бланки A4) и `3B-350B` (этикетки 58×38).
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    LEGACY_ISSUED_STATUSES,
    LEGACY_STATUS_MAP,
    Client,
    Repair,
    RepairStatus,
    Setting,
)
from app.services.numbering import normalize_phone
from app.services.settings import get_setting, set_setting

log = logging.getLogger("msb.datamigrate")

MIGRATIONS_KEY = "data_migrations"


async def _applied(db: AsyncSession) -> dict:
    value = await get_setting(db, MIGRATIONS_KEY, default={}) or {}
    return value if isinstance(value, dict) else {}


async def _mark_applied(db: AsyncSession, name: str, info: dict) -> None:
    applied = await _applied(db)
    applied[name] = info
    await set_setting(db, MIGRATIONS_KEY, applied, "Применённые миграции данных")


async def reindex_client_phones(db: AsyncSession) -> dict:
    """Пересчитать `phone_norm` у существующих клиентов под туркменский формат.

    Дубликаты, которые старая логика уже успела создать, объединяются:
    все ремонты переводятся на «выжившего» клиента (у кого больше ремонтов,
    а при равенстве — у кого запись старше), лишние записи помечаются
    удалёнными. Имя объединённого клиента не перезаписывается — расхождение
    попадает в `meta`, чтобы админ разобрал его вручную.
    """
    rows = await db.execute(select(Client).order_by(Client.created_at))
    clients = list(rows.scalars().all())

    by_norm: dict[str, list[Client]] = {}
    recalculated = 0
    for client in clients:
        new_norm = normalize_phone(client.phone or "")
        if not new_norm:
            continue
        if new_norm != client.phone_norm:
            client.phone_norm = new_norm
            recalculated += 1
        by_norm.setdefault(new_norm, []).append(client)

    merged = 0
    kept_names: list[dict] = []
    for norm, group in by_norm.items():
        if len(group) < 2:
            continue
        # «Выживает» клиент с наибольшим числом ремонтов, затем — самый старый.
        survivor = max(
            group,
            key=lambda c: (len(c.repairs), -(c.created_at.timestamp() if c.created_at else 0)),
        )
        for dup in group:
            if dup.id == survivor.id:
                continue
            from app.db.models import Repair

            await db.execute(
                Repair.__table__.update()
                .where(Repair.client_id == dup.id)
                .values(client_id=survivor.id)
            )
            dup.deleted_at = dup.deleted_at or survivor.created_at
            merged += 1
            if (dup.full_name or "") != (survivor.full_name or ""):
                kept_names.append(
                    {
                        "phone_norm": norm,
                        "kept": survivor.full_name,
                        "merged_away": dup.full_name,
                    }
                )

    await db.flush()
    return {"recalculated": recalculated, "merged": merged, "name_conflicts": kept_names}


async def migrate_repair_statuses(db: AsyncSession) -> dict:
    """Перевести ремонты на пять актуальных статусов.

    Раньше статусов было десять, и часть из них описывала не этап работы, а
    факт: «Выдано» (клиент забрал технику), «Не забрано», «Архив», «Отказ».
    Теперь статус один из пяти (`RepairStatus`), а факты живут в полях:
    выдачу фиксирует `issued_at`, готовность — `ready_at`.

    Заодно:
    * у ремонтов со старым статусом «Выдано» проставляем `issued_at`
      (иначе подсветка «забрал, но не оплатил» потеряла бы историю);
    * у завершённых без `ready_at` проставляем дату приёмки — иначе полоска
      «готово, но всё ещё в сервисе» не знала бы, с какого дня считать;
    * сохранённый в настройках список статусов приводим к актуальному.
    """
    rows = await db.execute(select(Repair))
    repairs = list(rows.scalars().all())

    renamed = 0
    issued_backfilled = 0
    ready_backfilled = 0
    for repair in repairs:
        old_status = repair.status
        new_status = LEGACY_STATUS_MAP.get(old_status)
        if new_status is None:
            continue
        repair.status = new_status
        renamed += 1
        if old_status in LEGACY_ISSUED_STATUSES and repair.issued_at is None:
            repair.issued_at = repair.ready_at or repair.accepted_at
            issued_backfilled += 1
        if new_status == RepairStatus.DONE and repair.ready_at is None:
            repair.ready_at = repair.accepted_at
            ready_backfilled += 1

    # Список статусов в настройках: если там ещё старые значения — заменяем.
    statuses_reset = False
    row = await db.execute(select(Setting).where(Setting.key == "repair_statuses"))
    setting = row.scalars().first()
    if setting is not None:
        items = (setting.value or {}).get("items")
        if isinstance(items, list) and any(
            str(x) not in RepairStatus.ALL for x in items
        ):
            setting.value = {"items": list(RepairStatus.ALL)}
            statuses_reset = True

    await db.flush()
    return {
        "renamed": renamed,
        "issued_backfilled": issued_backfilled,
        "ready_backfilled": ready_backfilled,
        "settings_reset": statuses_reset,
        "statuses": list(RepairStatus.ALL),
    }


# Названия очередей, которые считаются устаревшими: пустое имя (ничего не
# задано) и значения прошлой схемы — Epson L3250 по USB на рабочей машине для
# бланков и `label58` для этикеток. Очередь `3B-350B` раньше была расшарена
# CUPS на другом компьютере и теперь переехала в CUPS самого сервера MSB,
# поэтому её сохранённый `cups_remote` тоже приводится к локальной очереди.
LEGACY_A4_NAMES = ("", "epson l3250", "epson_l3250")
LEGACY_LABEL_NAMES = ("", "label58", "3b-350b")


async def align_cups_queues(db: AsyncSession) -> dict:
    """Привести настройки печати к двум очередям CUPS самого сервера MSB.

    Оба принтера подключены к CUPS на той же машине, где работает MSB и
    print-agent:

      `office_printer_a4` — бланки A4;
      `3B-350B`           — этикетки 58×38 мм.

    Поэтому режим `cups_local` (нужно только имя очереди, адрес знает CUPS)
    вытесняет прежние схемы: драйвер ОС для бланков (`agent` + `MSB_PRINT_CMD`
    с Epson L3250) и удалённый CUPS для этикеток. Намеренно заданные варианты
    не трогаем: `ipp`/`cups_remote` для бланков и чужое имя очереди для
    этикеток остаются как есть — администратор настроил их сам.
    """
    from app.services.settings import DEFAULT_A4_QUEUE, DEFAULT_LABEL_QUEUE

    changed: dict[str, str] = {}

    printer = await get_setting(db, "printer") or {}
    mode = str(printer.get("mode") or "").strip()
    name = str(printer.get("name") or "").strip()
    if mode == "agent" and name.lower() in LEGACY_A4_NAMES:
        await set_setting(
            db,
            "printer",
            {"ip": "", "port": 631, "mode": "cups_local", "name": DEFAULT_A4_QUEUE},
            "Принтер бланков A4: очередь CUPS, режим печати",
        )
        changed["printer"] = f"{mode}/{name or '—'} → cups_local/{DEFAULT_A4_QUEUE}"

    label = await get_setting(db, "label_printer") or {}
    label_mode = str(label.get("mode") or "").strip()
    label_name = str(label.get("name") or "").strip()
    if label_mode == "cups_remote" and label_name.lower() in LEGACY_LABEL_NAMES:
        value = dict(label)
        value.update(
            ip="", mode="cups_local", name=DEFAULT_LABEL_QUEUE,
            width_mm=58, height_mm=38,
        )
        await set_setting(db, "label_printer", value, "CUPS-принтер этикеток 58×38 мм")
        changed["label_printer"] = (
            f"{label_mode}/{label_name or '—'} → cups_local/{DEFAULT_LABEL_QUEUE}"
        )

    return changed or {"ok": True}


async def raw_tspl_label_v1(db: AsyncSession) -> dict:
    """Принтер этикеток — не в CUPS: raw-сокет TSPL 192.168.8.75:9100.

    Этикеточный принтер не подключён к CUPS: он слушает порт 9100 и читает
    язык TSPL, поэтому режим `cups_local` из `cups_local_queues_v1` для него
    неработоспособен. Переводим этикетки на `raw_tspl` с адресом из env
    `MSB_LABEL_HOST`/`MSB_LABEL_PORT` (по умолчанию 192.168.8.75:9100). Бланки
    A4 при этом остаются в очереди `office_printer_a4`.

    Если администратор уже настроил `raw_tspl` вручную, не трогаем.
    """
    from app.services.settings import (
        DEFAULT_LABEL_HOST,
        DEFAULT_LABEL_PORT,
        DEFAULT_LABEL_QUEUE,
    )

    label = await get_setting(db, "label_printer") or {}
    if str(label.get("mode") or "") == "raw_tspl":
        return {"ok": True}

    value = dict(label)
    value.update(
        mode="raw_tspl",
        ip=DEFAULT_LABEL_HOST,
        port=DEFAULT_LABEL_PORT,
        name=value.get("name") or DEFAULT_LABEL_QUEUE,
        width_mm=58,
        height_mm=38,
        gap_mm=2,
        media="Custom.58x38mm",
    )
    await set_setting(db, "label_printer", value, "Принтер этикеток 58×38 мм (raw TSPL)")
    return {
        "label_printer": f"{label.get('mode') or '—'}/{label.get('name') or '—'} → "
        f"raw_tspl/{DEFAULT_LABEL_HOST}:{DEFAULT_LABEL_PORT}"
    }


# Реестр миграций: имя -> функция. Порядок не важен (каждая идемпотентна).
MIGRATIONS = {
    "client_phone_norm_v2": reindex_client_phones,
    "repair_statuses_v2": migrate_repair_statuses,
    "cups_local_queues_v1": align_cups_queues,
    "raw_tspl_label_v1": raw_tspl_label_v1,
}


async def run_data_migrations(db: AsyncSession) -> list[str]:
    """Применить ещё не выполненные миграции данных. Возвращает их имена."""
    applied_now: list[str] = []
    applied = await _applied(db)

    for name, fn in MIGRATIONS.items():
        if name in applied:
            continue
        try:
            info = await fn(db)
        except Exception as exc:  # noqa: BLE001 — старт API не должен падать
            log.error("миграция данных %s не выполнена: %s", name, exc)
            await db.rollback()
            continue
        await _mark_applied(db, name, info if isinstance(info, dict) else {"ok": True})
        applied_now.append(name)
        log.info("миграция данных %s применена: %s", name, info)

    if applied_now:
        await db.commit()
    return applied_now
