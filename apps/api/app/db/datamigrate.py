"""Одноразовые миграции ДАННЫХ (в отличие от `db/migrate.py` — про колонки).

`Base.metadata.create_all` создаёт таблицы, `db/migrate.py` добавляет колонки,
но neither не умеет пересчитать уже лежащие в БД значения. Здесь — список
идемпотентных пересчётов, каждый помечается применённым в
`Setting["data_migrations"]`, поэтому при следующем старте не повторяется.

Сейчас здесь одна миграция: `client_phone_norm_v2`. Старая `normalize_phone()`
была написана под российские коды 7/8 и не приводила туркменские номера к
единому виду, из-за чего один человек, записанный как «+993 61 234567» и как
«8 61 234567», получал две разные записи в `clients`.
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


# Реестр миграций: имя -> функция. Порядок не важен (каждая идемпотентна).
MIGRATIONS = {
    "client_phone_norm_v2": reindex_client_phones,
    "repair_statuses_v2": migrate_repair_statuses,
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
