"""Экспорт и импорт данных (резервная копия) в формате `msb_backup.zip`.

Архив:

    msb_backup.zip
    ├── meta.json          — метаданные: дата, кто выгрузил, число записей
    ├── msb_export.json    — данные: {"version", "exported_at", "tables": {...}}
    └── media/…            — (опционально) файлы фотографий ремонтов

Таблицы в `msb_export.json` соответствуют шаблону обмена (см. README,
раздел «Резервная копия»): clients, repairs, repair_masters, repair_parts,
repair_history, repair_number_aliases, donor_units, donor_parts,
app_settings, sms_log, print_log. Сверх шаблона выгружаются служебные
таблицы (users, cities, branches, payments, repair_part_orders, parts,
price_items, equipment) — они нужны, чтобы восстановление на чистой базе
было полным. Импорт понимает как «наш» формат, так и выгрузку старой базы:
`device_type` вместо `category`, `serial` вместо `serial_number`,
`complectation` вместо `equipment_json`, `name` вместо `full_name`,
строковые идентификаторы вида `c-100` / `r-200` и целые id пользователей.

Деньги в файле — в копейках/тенне (`*_cents`), в БД — Numeric(12,2).
Даты — строки `YYYY-MM-DD HH:MM:SS` (UTC, без смещения).

Импорт идемпотентен: повторная загрузка того же файла ничего не дублирует.
Записи сопоставляются по UUID (если id — UUID и такая строка есть), иначе
по естественному ключу: клиент — по нормализованному телефону, ремонт — по
номеру, мастер на ремонте — по паре (ремонт, сотрудник) и т.д.
"""
from __future__ import annotations

import io
import json
import logging
import re
import secrets
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings as app_settings
from app.core.security import hash_password
from app.db.models import (
    LEGACY_ISSUED_STATUSES,
    Branch,
    City,
    Client,
    DonorPart,
    DonorUnit,
    Equipment,
    Notification,
    Part,
    Payment,
    PriceItem,
    PrintJob,
    Repair,
    RepairEvent,
    RepairMaster,
    RepairPart,
    RepairPartOrder,
    RepairPhoto,
    RepairStatus,
    Setting,
    User,
    UserRole,
    map_status,
)
from app.services.numbering import new_public_token, next_repair_number, normalize_phone
from app.webui.catalog import normalize_class
from app.webui.intake_form import COND_LABELS, EQUIP_LABELS

log = logging.getLogger("msb.backup")

FORMAT_VERSION = "1.0"
DATA_FILE = "msb_export.json"
META_FILE = "meta.json"
MEDIA_DIR = "media"
# Имена файла с данными, которые понимает импорт (наш и «старый» варианты).
DATA_FILE_CANDIDATES = (DATA_FILE, "data.json", "export.json")

# Ключ в settings, где хранятся псевдонимы старых номеров ремонтов
# (`repair_number_aliases`): {"items": {"MSB-00123": "<uuid ремонта>"}}.
ALIASES_KEY = "repair_number_aliases"

# Настройки, которые при импорте не трогаем: журнал миграций данных привязан к
# конкретной базе, а IP-контроль из чужой базы может заблокировать админа.
PROTECTED_SETTINGS = {"data_migrations", "ip_control"}

# Порядок таблиц в файле (шаблон обмена — первыми).
TABLE_ORDER = (
    "clients",
    "repairs",
    "repair_masters",
    "repair_parts",
    "repair_history",
    "repair_number_aliases",
    "donor_units",
    "donor_parts",
    "app_settings",
    "sms_log",
    "print_log",
    # служебные (сверх шаблона)
    "users",
    "cities",
    "branches",
    "payments",
    "repair_part_orders",
    "parts",
    "price_items",
    "equipment",
)

# Подписи таблиц для страницы админки.
TABLE_LABELS = {
    "clients": "Клиенты",
    "repairs": "Ремонты",
    "repair_masters": "Мастера на ремонтах",
    "repair_parts": "Запчасти в ремонтах",
    "repair_history": "История ремонтов",
    "repair_number_aliases": "Старые номера ремонтов",
    "donor_units": "Склад разбора: техника",
    "donor_parts": "Склад разбора: запчасти",
    "app_settings": "Настройки",
    "sms_log": "Журнал SMS",
    "print_log": "Журнал печати",
    "users": "Сотрудники",
    "cities": "Города",
    "branches": "Точки",
    "payments": "Платежи (касса)",
    "repair_part_orders": "Заказы запчастей",
    "parts": "Склад запчастей",
    "price_items": "Прайс-лист",
    "equipment": "Купленная техника",
    "repair_photos": "Фотографии",
}

_EQUIP_CODE_BY_LABEL = {v: k for k, v in EQUIP_LABELS.items()}
_COND_CODE_BY_LABEL = {v: k for k, v in COND_LABELS.items()}


# ==========================================================================
# Общие помощники: даты, деньги, JSON, идентификаторы
# ==========================================================================
def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fmt_dt(value) -> str | None:
    """datetime → 'YYYY-MM-DD HH:MM:SS' (None остаётся None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def fmt_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


_DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
)


def parse_dt(value) -> datetime | None:
    """Строка/число из файла → naive UTC datetime. Мусор → None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        dt = None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in _DT_FORMATS:
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(value) -> date | None:
    dt = parse_dt(value)
    return dt.date() if dt else None


def to_cents(value) -> int | None:
    """Numeric/float из БД → целые копейки для файла."""
    if value is None or value == "":
        return None
    try:
        return int((Decimal(str(value)) * 100).to_integral_value())
    except (ArithmeticError, ValueError):
        return None


def from_cents(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)) / 100)
    except (ArithmeticError, ValueError):
        return None


def _money_in(rec: dict, name: str) -> float | None:
    """Сумма из записи: сначала `<name>_cents`, иначе `<name>` (в манатах)."""
    if f"{name}_cents" in rec and rec[f"{name}_cents"] not in (None, ""):
        return from_cents(rec[f"{name}_cents"])
    raw = rec.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(str(raw).replace(",", "."))
    except ValueError:
        return None


def jdump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def jload(value, default):
    """Поле *_json может прийти строкой JSON или уже разобранным значением."""
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default


def _uuid(value) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _s(value, limit: int | None = None) -> str | None:
    """Строка или None; при `limit` — обрезка под ширину колонки."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if limit and len(text) > limit:
        text = text[:limit]
    return text


def _int(value, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(float(str(value)))
    except ValueError:
        return default


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on", "да")


def _first(rec: dict, *names, default=None):
    """Первое присутствующее поле из списка синонимов."""
    for n in names:
        if n in rec and rec[n] is not None:
            return rec[n]
    return default


# ==========================================================================
# Комплектация / состояние / гарантия ↔ поля шаблона
# ==========================================================================
def equipment_out(complectation: dict | None) -> tuple[list[str], str]:
    """{«Пульт»: True, «Сумка»: True} → (["remote"], "Сумка")."""
    codes: list[str] = []
    other: list[str] = []
    if isinstance(complectation, dict):
        # Два формата в БД: {"items": ["Пульт", …]} (JSON-API) и
        # {"Пульт": true, …} (веб-форма приёмки).
        items = []
        raw_items = complectation.get("items")
        if isinstance(raw_items, list):
            items.extend(str(x) for x in raw_items)
        elif isinstance(raw_items, str):
            items.extend(x.strip() for x in raw_items.split(",") if x.strip())
        items.extend(k for k, v in complectation.items() if k != "items" and v)
    elif isinstance(complectation, list):
        items = [str(x) for x in complectation]
    else:
        items = []
    for label in items:
        label = str(label).strip()
        if not label:
            continue
        code = _EQUIP_CODE_BY_LABEL.get(label)
        if code:
            codes.append(code)
        else:
            other.append(label)
    return codes, ", ".join(other)


def _complectation_labels(value) -> list[str]:
    """Любое представление комплектации → список подписей.

    Понимает: {"items": [...]}, {"Пульт": true}, ["remote", "Сумка"],
    строку JSON и строку «через запятую». Коды формы (remote, legs…)
    переводятся в подписи.
    """
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parsed = jload(value, None)
        if isinstance(parsed, (list, dict)):
            return _complectation_labels(parsed)
        return [x.strip() for x in value.split(",") if x.strip()]
    labels: list[str] = []
    if isinstance(value, dict):
        raw_items = value.get("items")
        if isinstance(raw_items, (list, str)):
            labels.extend(_complectation_labels(raw_items))
        labels.extend(str(k).strip() for k, v in value.items() if k != "items" and v and str(k).strip())
    elif isinstance(value, list):
        labels.extend(str(x).strip() for x in value if str(x).strip())
    return [EQUIP_LABELS.get(x, x) for x in labels]


def equipment_in(rec: dict) -> dict | None:
    """equipment_json + equipment_other (или complectation старой базы) → dict.

    Если в записи есть `complectation`-словарь (наш собственный экспорт),
    он берётся как есть — так формат в БД не меняется при восстановлении.
    """
    raw = rec.get("complectation")
    if isinstance(raw, dict):
        return raw or None
    comp: dict[str, bool] = {}
    for label in _complectation_labels(_first(rec, "equipment_json", "equipment", "complectation_json")):
        comp[label] = True
    for label in _complectation_labels(raw):
        comp[label] = True
    for label in _complectation_labels(rec.get("equipment_other")):
        comp[label] = True
    return comp or None


def condition_out(notes: str | None) -> tuple[list[str], str]:
    """'Царапины на корпусе; трещина' → (["body_scratches"], "трещина")."""
    codes: list[str] = []
    other: list[str] = []
    for part in re.split(r"[;,]", notes or ""):
        text = part.strip()
        if not text:
            continue
        code = _COND_CODE_BY_LABEL.get(text)
        if code:
            codes.append(code)
        else:
            other.append(text)
    return codes, ", ".join(other)


def condition_in(rec: dict) -> str | None:
    parts: list[str] = []
    raw = _first(rec, "condition_json", "condition")
    for item in jload(raw, []) or []:
        text = str(item).strip()
        if text:
            parts.append(COND_LABELS.get(text, text))
    other = _s(_first(rec, "condition_other", "condition_notes"))
    if other:
        for item in other.split(","):
            if item.strip() and item.strip() not in parts:
                parts.append(item.strip())
    return "; ".join(parts) or None


_WARRANTY_RE = re.compile(r"(\d+)\s*([^\W\d_]+)", re.IGNORECASE | re.UNICODE)


def warranty_days(text: str | None) -> int | None:
    """'90 дней' / '3 aý' / '1 год' → число дней (None, если не разобрать)."""
    if not text:
        return None
    m = _WARRANTY_RE.search(str(text))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith(("дн", "ден", "gün", "gun", "day")):
        return n
    if unit.startswith(("мес", "aý", "ay", "mon")):
        return n * 30
    if unit.startswith(("год", "лет", "ýyl", "yyl", "year")):
        return n * 365
    if unit.startswith(("нед", "hep", "week")):
        return n * 7
    return None


# ==========================================================================
# Экспорт
# ==========================================================================
async def export_tables(db: AsyncSession) -> dict[str, list[dict]]:
    """Собрать все таблицы файла обмена из БД."""
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    user_name = {u.id: u.name for u in users}
    cities = (await db.execute(select(City).order_by(City.created_at))).scalars().all()
    city_slug = {c.id: c.slug for c in cities}
    branches = (await db.execute(select(Branch).order_by(Branch.created_at))).scalars().all()
    branch_name = {b.id: b.name for b in branches}

    clients = (await db.execute(select(Client).order_by(Client.created_at))).scalars().all()
    repairs = (
        await db.execute(
            select(Repair)
            .order_by(Repair.accepted_at)
            .options(selectinload(Repair.masters).selectinload(RepairMaster.user))
        )
    ).scalars().all()
    payments = (await db.execute(select(Payment).order_by(Payment.paid_at))).scalars().all()
    photos = (await db.execute(select(RepairPhoto).order_by(RepairPhoto.created_at))).scalars().all()
    repair_parts = (
        await db.execute(
            select(RepairPart).order_by(RepairPart.created_at).options(selectinload(RepairPart.part))
        )
    ).scalars().all()
    part_orders = (
        await db.execute(select(RepairPartOrder).order_by(RepairPartOrder.created_at))
    ).scalars().all()
    events = (await db.execute(select(RepairEvent).order_by(RepairEvent.created_at))).scalars().all()
    donors = (await db.execute(select(DonorUnit).order_by(DonorUnit.created_at))).scalars().all()
    donor_parts = (await db.execute(select(DonorPart).order_by(DonorPart.created_at))).scalars().all()
    settings_rows = (await db.execute(select(Setting).order_by(Setting.key))).scalars().all()
    print_jobs = (await db.execute(select(PrintJob).order_by(PrintJob.created_at))).scalars().all()
    parts = (await db.execute(select(Part).order_by(Part.created_at))).scalars().all()
    prices = (await db.execute(select(PriceItem).order_by(PriceItem.created_at))).scalars().all()
    equipment = (await db.execute(select(Equipment).order_by(Equipment.created_at))).scalars().all()

    paid_by_repair: dict[uuid.UUID, int] = {}
    for p in payments:
        paid_by_repair[p.repair_id] = paid_by_repair.get(p.repair_id, 0) + (to_cents(p.amount) or 0)
    photos_by_repair: dict[uuid.UUID, list[dict]] = {}
    for ph in photos:
        photos_by_repair.setdefault(ph.repair_id, []).append(
            {
                "id": str(ph.id),
                "object_key": ph.object_key,
                "thumb_key": ph.thumb_key,
                "caption": ph.caption,
                "created_at": fmt_dt(ph.created_at),
            }
        )

    t: dict[str, list[dict]] = {name: [] for name in TABLE_ORDER}

    for c in clients:
        t["clients"].append(
            {
                "id": str(c.id),
                "name": c.full_name,
                "full_name": c.full_name,
                "phone": c.phone,
                "phone_norm": c.phone_norm,
                "extra_phones_json": "[]",
                "consent_pdn_at": fmt_dt(c.consent_pdn_at),
                "consent_storage_at": fmt_dt(c.consent_storage_at),
                "created_at": fmt_dt(c.created_at),
                "updated_at": fmt_dt(c.updated_at),
                "deleted_at": fmt_dt(c.deleted_at),
            }
        )

    for r in repairs:
        eq_codes, eq_other = equipment_out(r.complectation)
        cond_codes, cond_other = condition_out(r.condition_notes)
        w_days = warranty_days(r.warranty_text)
        w_start = (r.ready_at or r.issued_at) if r.warranty_text else None
        w_until = (w_start + timedelta(days=w_days)) if (w_start and w_days) else None
        t["repairs"].append(
            {
                "id": str(r.id),
                "number": r.number,
                "public_token": r.public_token,
                "client_id": str(r.client_id),
                "category": r.device_type,
                "brand": r.brand,
                "model": r.model,
                "serial_number": r.serial,
                "fault_client": r.fault_client,
                "work_done": r.work_done,
                "diagnosis": r.fault_master,
                "equipment_json": jdump(eq_codes),
                "equipment_other": eq_other,
                # Сырое значение как в БД — для точного восстановления
                # (equipment_json/equipment_other — для совместимости со старой базой).
                "complectation": r.complectation,
                "condition_json": jdump(cond_codes),
                "condition_other": cond_other,
                "photos_json": jdump(photos_by_repair.get(r.id, [])),
                "is_delivery": int(bool(r.is_delivery)),
                "delivery_district": r.delivery_district,
                "delivery_person": "",
                "delivery_phone": r.delivery_courier_phone,
                "delivery_fee_cents": 0,
                "delivery_comment": r.delivery_comment,
                "accepted_by_id": str(r.accepted_by) if r.accepted_by else None,
                "accepted_by_name": user_name.get(r.accepted_by),
                "status": r.status,
                "price_min_cents": to_cents(r.price_min),
                "price_max_cents": to_cents(r.price_max),
                "price_final_cents": to_cents(r.price_final),
                "paid_cents": paid_by_repair.get(r.id, 0),
                "payment_mark": int(bool(r.paid)),
                "master_payout_cents": to_cents(r.master_payout),
                "cost_cents": to_cents(r.cost_amount),
                "warranty_text": r.warranty_text,
                "warranty_start": fmt_date(w_start),
                "warranty_until": fmt_date(w_until),
                "responsible_master_id": str(r.master_id) if r.master_id else None,
                "responsible_master_name": user_name.get(r.master_id),
                "eta_days": r.eta_days,
                "eta_source": r.eta_source,
                "source": r.source,
                "print_count": r.print_count,
                "contact2_name": r.contact2_name,
                "contact2_phone": r.contact2_phone,
                "contact2_relation": r.contact2_relation,
                "consent_repair_at": fmt_dt(r.consent_repair_at),
                "city_slug": city_slug.get(r.city_id),
                "branch_name": branch_name.get(r.branch_id),
                "accepted_at": fmt_dt(r.accepted_at),
                "finished_at": fmt_dt(r.ready_at),
                "issued_at": fmt_dt(r.issued_at),
                "storage_until": fmt_dt(r.storage_until),
                "created_at": fmt_dt(r.created_at),
                "updated_at": fmt_dt(r.updated_at),
                "deleted_at": None,
            }
        )
        for link in r.masters:
            is_master = (link.kind or "master") != "helper"
            t["repair_masters"].append(
                {
                    "repair_id": str(r.id),
                    "user_id": str(link.user_id),
                    "display_name": link.user.name if link.user else user_name.get(link.user_id),
                    "assignment_role": "master" if is_master else "assistant",
                    "position": link.position,
                    "reward_cents": (
                        to_cents(r.master_payout) or 0
                        if (is_master and link.user_id == r.master_id)
                        else 0
                    ),
                }
            )

    for rp in repair_parts:
        t["repair_parts"].append(
            {
                "id": str(rp.id),
                "repair_id": str(rp.repair_id),
                "part_id": str(rp.part_id),
                "name": rp.part.name if rp.part else "",
                "quantity": rp.qty,
                "unit_cost_cents": to_cents(rp.price),
                "is_manual": int(bool(rp.is_manual)),
                "created_at": fmt_dt(rp.created_at),
            }
        )

    for e in events:
        data = e.data if isinstance(e.data, dict) else {}
        comment = data.get("message")
        if not comment and e.type == "status_change":
            comment = f"{data.get('from') or '—'} → {data.get('to') or '—'}"
        t["repair_history"].append(
            {
                "id": str(e.id),
                "repair_id": str(e.repair_id),
                "event_type": e.type,
                "actor_user_id": str(e.actor_id) if e.actor_id else None,
                "actor_name": user_name.get(e.actor_id),
                "comment": comment or "",
                "details_json": jdump(data),
                "created_at": fmt_dt(e.created_at),
            }
        )
        if e.type == "notify":
            t["sms_log"].append(
                {
                    "id": str(e.id),
                    "repair_id": str(e.repair_id),
                    "kind": data.get("kind") or "sms",
                    "phone": data.get("phone"),
                    "text": data.get("sms_text") or comment or "",
                    "status": "sent" if data.get("ok", True) else "failed",
                    "detail": data.get("detail"),
                    "actor_user_id": str(e.actor_id) if e.actor_id else None,
                    "created_at": fmt_dt(e.created_at),
                }
            )

    aliases_setting = next((s for s in settings_rows if s.key == ALIASES_KEY), None)
    alias_items = (aliases_setting.value or {}).get("items") if aliases_setting else None
    if isinstance(alias_items, dict):
        for old_number, repair_id in sorted(alias_items.items()):
            t["repair_number_aliases"].append(
                {"old_number": old_number, "repair_id": str(repair_id)}
            )

    for d in donors:
        t["donor_units"].append(
            {
                "id": str(d.id),
                "brand": d.brand,
                "model": d.model,
                "serial_number": "",
                "board_number": "",
                "comment": d.comment,
                "created_by_id": str(d.created_by_id) if d.created_by_id else None,
                "created_by_name": user_name.get(d.created_by_id),
                "created_at": fmt_dt(d.created_at),
                "updated_at": fmt_dt(d.updated_at),
            }
        )
    for dp in donor_parts:
        t["donor_parts"].append(
            {
                "id": str(dp.id),
                "donor_id": str(dp.donor_id),
                "name": dp.name,
                "quantity": 1,
                "panel_number": dp.panel_number,
                "price_cents": to_cents(dp.price_sale),
                "comment": dp.comment,
                "created_at": fmt_dt(dp.created_at),
            }
        )

    for s in settings_rows:
        t["app_settings"].append(
            {
                "key": s.key,
                "value_json": jdump(s.value),
                "description": s.description,
                "updated_at": fmt_dt(s.updated_at),
            }
        )

    for j in print_jobs:
        payload = j.payload if isinstance(j.payload, dict) else {}
        t["print_log"].append(
            {
                "id": str(j.id),
                "repair_id": str(j.repair_id) if j.repair_id else None,
                "kind": payload.get("kind") or "blank",
                "template_id": j.template_id,
                "status": j.status,
                "attempts": j.attempts,
                "error": j.error,
                "sent_at": fmt_dt(j.sent_at),
                "created_at": fmt_dt(j.created_at),
            }
        )

    for u in users:
        t["users"].append(
            {
                "id": str(u.id),
                "name": u.name,
                "email": u.email,
                "phone": u.phone,
                "telegram": u.telegram,
                "role": u.role,
                "extra_roles_json": jdump(list(u.extra_roles or [])),
                "permissions_json": jdump(list(u.extra_permissions or [])),
                "active": int(bool(u.active)),
                "password_hash": u.password_hash,
                "city_slug": city_slug.get(u.city_id),
                "branch_name": branch_name.get(u.branch_id),
                "created_at": fmt_dt(u.created_at),
                "updated_at": fmt_dt(u.updated_at),
            }
        )
    for c in cities:
        t["cities"].append(
            {"id": str(c.id), "slug": c.slug, "name": c.name, "timezone": c.timezone,
             "created_at": fmt_dt(c.created_at)}
        )
    for b in branches:
        t["branches"].append(
            {
                "id": str(b.id),
                "city_slug": city_slug.get(b.city_id),
                "name": b.name,
                "address": b.address,
                "phone": b.phone,
                "print_config_json": jdump(b.print_config),
                "active": int(bool(b.active)),
                "created_at": fmt_dt(b.created_at),
            }
        )
    for p in payments:
        t["payments"].append(
            {
                "id": str(p.id),
                "repair_id": str(p.repair_id),
                "amount_cents": to_cents(p.amount),
                "method": p.method,
                "operator_id": str(p.operator_id) if p.operator_id else None,
                "operator_name": user_name.get(p.operator_id),
                "paid_at": fmt_dt(p.paid_at),
                "created_at": fmt_dt(p.created_at),
            }
        )
    for o in part_orders:
        t["repair_part_orders"].append(
            {
                "id": str(o.id),
                "repair_id": str(o.repair_id),
                "name": o.name,
                "quantity": o.qty,
                "price_cents": to_cents(o.price),
                "ordered_at": fmt_dt(o.ordered_at),
                "received_at": fmt_dt(o.received_at),
                "created_by_id": str(o.created_by) if o.created_by else None,
                "created_at": fmt_dt(o.created_at),
            }
        )
    for p in parts:
        t["parts"].append(
            {
                "id": str(p.id),
                "name": p.name,
                "sku": p.sku,
                "category": p.category,
                "stock_qty": p.stock_qty,
                "min_stock": p.min_stock,
                "cost_price_cents": to_cents(p.cost_price),
                "sell_price_cents": to_cents(p.sell_price),
                "supplier": p.supplier,
                "active": int(bool(p.active)),
                "created_at": fmt_dt(p.created_at),
                "updated_at": fmt_dt(p.updated_at),
            }
        )
    for pi in prices:
        t["price_items"].append(
            {
                "id": str(pi.id),
                "device_type": pi.device_type,
                "brand": pi.brand,
                "model_or_line": pi.model_or_line,
                "fault": pi.fault,
                "city_slug": city_slug.get(pi.city_id),
                "price_min_cents": to_cents(pi.price_min),
                "price_max_cents": to_cents(pi.price_max),
                "price_avg_cents": to_cents(pi.price_avg),
                "typical_days": pi.typical_days,
                "source": pi.source,
                "active": int(bool(pi.active)),
                "created_at": fmt_dt(pi.created_at),
            }
        )
    for eq in equipment:
        t["equipment"].append(
            {
                "id": str(eq.id),
                "name": eq.name,
                "brand": eq.brand,
                "model": eq.model,
                "purchase_price_cents": to_cents(eq.purchase_price),
                "purchased_at": fmt_dt(eq.purchased_at),
                "status": eq.status,
                "components_json": jdump(list(eq.components or [])),
                "storage_place": eq.storage_place,
                "notes": eq.notes,
                "active": int(bool(eq.active)),
                "created_at": fmt_dt(eq.created_at),
                "updated_at": fmt_dt(eq.updated_at),
            }
        )

    return t


async def build_export(db: AsyncSession, *, exported_by: str | None = None) -> dict:
    tables = await export_tables(db)
    return {
        "version": FORMAT_VERSION,
        "app": "MSB",
        "exported_at": fmt_dt(_utcnow()),
        "exported_by": exported_by,
        "tables": tables,
    }


def _media_files(tables: dict[str, list[dict]]) -> list[str]:
    """Ключи файлов фотографий, упомянутых в выгрузке (только локальное хранилище)."""
    if app_settings.STORAGE_MODE != "local":
        return []
    keys: list[str] = []
    for r in tables.get("repairs", []):
        for ph in jload(r.get("photos_json"), []) or []:
            if isinstance(ph, dict):
                for k in (ph.get("object_key"), ph.get("thumb_key")):
                    if k:
                        keys.append(str(k))
            elif isinstance(ph, str):
                keys.append(ph)
    return keys


def _safe_media_path(root: Path, key: str) -> Path | None:
    target = (root / key).resolve()
    if not str(target).startswith(str(root.resolve()) + "/") and target != root.resolve():
        return None
    return target


async def build_backup_zip(
    db: AsyncSession, *, exported_by: str | None = None, include_media: bool = False
) -> tuple[bytes, dict]:
    """Собрать архив. Возвращает (байты zip, meta)."""
    export = await build_export(db, exported_by=exported_by)
    tables = export["tables"]
    counts = {name: len(rows) for name, rows in tables.items()}

    buf = io.BytesIO()
    media_count = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if include_media:
            root = Path(app_settings.UPLOAD_DIR)
            for key in _media_files(tables):
                path = _safe_media_path(root, key)
                if path and path.is_file():
                    zf.write(path, f"{MEDIA_DIR}/{key}")
                    media_count += 1
        meta = {
            "app": "MSB",
            "format": "msb_backup",
            "version": FORMAT_VERSION,
            "exported_at": export["exported_at"],
            "exported_by": exported_by,
            "data_file": DATA_FILE,
            "record_count": sum(counts.values()),
            "tables": counts,
            "media_files": media_count,
        }
        zf.writestr(META_FILE, json.dumps(meta, ensure_ascii=False, indent=2))
        zf.writestr(DATA_FILE, json.dumps(export, ensure_ascii=False, indent=2))
    return buf.getvalue(), meta


def backup_filename(exported_at: str | None = None) -> str:
    stamp = (exported_at or fmt_dt(_utcnow()) or "").replace(":", "").replace(" ", "_")
    return f"msb_backup_{stamp}.zip" if stamp else "msb_backup.zip"


# ==========================================================================
# Импорт
# ==========================================================================
class ImportError_(ValueError):
    """Файл не распознан или импорт прерван — сообщение показывается админу."""


@dataclass
class TableStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped


@dataclass
class ImportReport:
    mode: str = "merge"
    tables: dict[str, TableStats] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    created_users: list[str] = field(default_factory=list)
    media_restored: int = 0
    error: str | None = None
    source_meta: dict = field(default_factory=dict)

    def stat(self, table: str) -> TableStats:
        return self.tables.setdefault(table, TableStats())

    def warn(self, text: str) -> None:
        if len(self.warnings) < 200:
            self.warnings.append(text)
        elif len(self.warnings) == 200:
            self.warnings.append("… (дальнейшие предупреждения скрыты)")

    @property
    def created(self) -> int:
        return sum(s.created for s in self.tables.values())

    @property
    def updated(self) -> int:
        return sum(s.updated for s in self.tables.values())

    @property
    def skipped(self) -> int:
        return sum(s.skipped for s in self.tables.values())

    def as_dict(self) -> dict:
        return {
            "ok": self.error is None,
            "mode": self.mode,
            "error": self.error,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "tables": {
                k: {"created": v.created, "updated": v.updated, "skipped": v.skipped}
                for k, v in self.tables.items()
            },
            "warnings": self.warnings,
            "created_users": self.created_users,
            "media_restored": self.media_restored,
            "source_meta": self.source_meta,
        }


def read_backup_file(data: bytes, filename: str = "") -> tuple[dict, dict, dict[str, bytes]]:
    """Распаковать загруженный файл: (payload, meta, media{key: bytes}).

    Принимает zip-архив (msb_export.json / data.json внутри) либо голый JSON.
    """
    if not data:
        raise ImportError_("Файл пустой")
    meta: dict = {}
    media: dict[str, bytes] = {}
    if data[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise ImportError_(f"Архив повреждён: {e}") from e
        names = zf.namelist()
        data_name = next((n for n in DATA_FILE_CANDIDATES if n in names), None)
        if data_name is None:
            # файл мог лежать в подпапке
            data_name = next(
                (n for n in names if n.rsplit("/", 1)[-1] in DATA_FILE_CANDIDATES), None
            )
        if data_name is None:
            json_names = [n for n in names if n.lower().endswith(".json") and not n.endswith(META_FILE)]
            if len(json_names) == 1:
                data_name = json_names[0]
        if data_name is None:
            raise ImportError_(
                f"В архиве нет файла данных ({', '.join(DATA_FILE_CANDIDATES)})"
            )
        meta_name = next((n for n in names if n.rsplit("/", 1)[-1] == META_FILE), None)
        if meta_name:
            try:
                meta = json.loads(zf.read(meta_name).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                meta = {}
        raw = zf.read(data_name)
        prefix = data_name.rsplit("/", 1)[0] + "/" if "/" in data_name else ""
        for n in names:
            rel = n[len(prefix):] if prefix and n.startswith(prefix) else n
            if rel.startswith(MEDIA_DIR + "/") and not n.endswith("/"):
                key = rel[len(MEDIA_DIR) + 1:]
                if key and ".." not in key.split("/"):
                    media[key] = zf.read(n)
    else:
        raw = data
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ImportError_(f"Файл данных не является корректным JSON: {e}") from e
    if not isinstance(payload, dict):
        raise ImportError_("Ожидался JSON-объект с ключом tables")
    if "tables" not in payload:
        # Допускаем «плоский» вариант: {"clients": [...], "repairs": [...]}
        if any(k in payload for k in ("clients", "repairs")):
            payload = {"version": payload.get("version", "1.0"), "tables": payload}
        else:
            raise ImportError_("В файле нет раздела tables")
    if not isinstance(payload["tables"], dict):
        raise ImportError_("Раздел tables должен быть объектом {таблица: [записи]}")
    return payload, meta, media


class _Ctx:
    """Состояние одного импорта: справочники и карты старых id → объектов."""

    def __init__(self, db: AsyncSession, actor: User, report: ImportReport):
        self.db = db
        self.actor = actor
        self.report = report
        self.users_by_id: dict[uuid.UUID, User] = {}
        self.users_by_email: dict[str, User] = {}
        self.users_by_name: dict[str, User] = {}
        self.user_refs: dict[str, User] = {}  # старые id из файла
        self.cities_by_id: dict[uuid.UUID, City] = {}
        self.cities_by_slug: dict[str, City] = {}
        self.city_refs: dict[str, City] = {}
        self.branches_by_id: dict[uuid.UUID, Branch] = {}
        self.branch_refs: dict[str, Branch] = {}
        self.default_city: City | None = None
        self.clients: dict[str, Client] = {}
        self.repairs: dict[str, Repair] = {}
        self.repairs_by_number: dict[str, Repair] = {}
        self.donors: dict[str, DonorUnit] = {}
        self.parts_by_name: dict[str, Part] = {}
        self.parts_by_id: dict[uuid.UUID, Part] = {}
        self.paid_hint: dict[uuid.UUID, int] = {}
        self.payout_hint: dict[uuid.UUID, int] = {}
        self.event_keys: dict[uuid.UUID, set] = {}
        self.event_ids: set[uuid.UUID] = set()
        self.history_ids: set[str] = set()

    # --- пользователи ---
    async def load(self) -> None:
        for u in (await self.db.execute(select(User))).scalars().all():
            self._index_user(u)
        for c in (await self.db.execute(select(City).order_by(City.created_at))).scalars().all():
            self.cities_by_id[c.id] = c
            self.cities_by_slug[c.slug.lower()] = c
            if self.default_city is None:
                self.default_city = c
        asg = self.cities_by_slug.get("asg")
        if asg is not None:
            self.default_city = asg
        for b in (await self.db.execute(select(Branch))).scalars().all():
            self.branches_by_id[b.id] = b
        for p in (await self.db.execute(select(Part))).scalars().all():
            self.parts_by_id[p.id] = p
            self.parts_by_name.setdefault(p.name.strip().lower(), p)

    def _index_user(self, u: User) -> None:
        self.users_by_id[u.id] = u
        self.users_by_email[(u.email or "").lower()] = u
        self.users_by_name.setdefault((u.name or "").strip().lower(), u)

    async def ensure_default_city(self) -> City:
        if self.default_city is None:
            city = City(slug="asg", name="Ашхабад", timezone="Asia/Ashgabat")
            self.db.add(city)
            await self.db.flush()
            self.cities_by_id[city.id] = city
            self.cities_by_slug["asg"] = city
            self.default_city = city
        return self.default_city

    def city_by_ref(self, ref, slug=None) -> City | None:
        if slug:
            c = self.cities_by_slug.get(str(slug).lower())
            if c:
                return c
        if ref is not None:
            c = self.city_refs.get(str(ref))
            if c:
                return c
            uid = _uuid(ref)
            if uid and uid in self.cities_by_id:
                return self.cities_by_id[uid]
        return None

    def branch_by_ref(self, ref, name=None, city: City | None = None) -> Branch | None:
        if ref is not None:
            b = self.branch_refs.get(str(ref))
            if b:
                return b
            uid = _uuid(ref)
            if uid and uid in self.branches_by_id:
                return self.branches_by_id[uid]
        if name:
            for b in self.branches_by_id.values():
                if b.name == name and (city is None or b.city_id == city.id):
                    return b
        return None

    async def user_by_ref(self, ref, name=None, *, create_role: str | None = None) -> User | None:
        """Найти сотрудника по старому id / UUID / имени; при `create_role` — создать."""
        if ref is not None and str(ref).strip():
            key = str(ref).strip()
            u = self.user_refs.get(key)
            if u:
                return u
            uid = _uuid(key)
            if uid and uid in self.users_by_id:
                return self.users_by_id[uid]
            if "@" in key and key.lower() in self.users_by_email:
                return self.users_by_email[key.lower()]
        clean_name = _s(name)
        if clean_name:
            u = self.users_by_name.get(clean_name.lower())
            if u:
                if ref is not None:
                    self.user_refs[str(ref).strip()] = u
                return u
            if create_role:
                # Неактивен и без известного пароля: админ включит его и
                # задаст пароль на странице «Сотрудники». Иначе «мёртвая»
                # учётка из старой базы попадала бы в списки назначения.
                u = User(
                    name=clean_name[:255],
                    email=f"import-{secrets.token_hex(4)}@msb.local",
                    password_hash=hash_password(secrets.token_urlsafe(24)),
                    role=create_role,
                    city_id=(await self.ensure_default_city()).id,
                    active=False,
                )
                self.db.add(u)
                await self.db.flush()
                self._index_user(u)
                if ref is not None:
                    self.user_refs[str(ref).strip()] = u
                self.report.created_users.append(f"{u.name} ({create_role}, {u.email}) — выключен, пароль не задан")
                return u
        return None

    # --- ремонты / клиенты ---
    def client_by_ref(self, ref) -> Client | None:
        if ref is None:
            return None
        return self.clients.get(str(ref).strip())

    def repair_by_ref(self, ref) -> Repair | None:
        if ref is None:
            return None
        key = str(ref).strip()
        r = self.repairs.get(key)
        if r:
            return r
        return self.repairs_by_number.get(key)

    async def preload_events(self, repair_ids: list[uuid.UUID]) -> None:
        missing = [rid for rid in repair_ids if rid not in self.event_keys]
        for rid in missing:
            self.event_keys[rid] = set()
        for i in range(0, len(missing), 500):
            chunk = missing[i:i + 500]
            rows = (
                await self.db.execute(select(RepairEvent).where(RepairEvent.repair_id.in_(chunk)))
            ).scalars().all()
            for e in rows:
                self.event_ids.add(e.id)
                self.event_keys[e.repair_id].add(self._event_key(e.type, e.created_at, e.data))

    @staticmethod
    def _event_key(etype: str, created_at, data) -> tuple:
        """Естественный ключ события для записей без UUID (старая база)."""
        d = data if isinstance(data, dict) else {}
        return (
            etype, fmt_dt(created_at), d.get("message") or "",
            str(d.get("from") or ""), str(d.get("to") or ""), str(d.get("kind") or ""),
        )

    async def part_by_name(self, name: str, *, part_ref=None, sell_price=None) -> Part:
        uid = _uuid(part_ref)
        if uid and uid in self.parts_by_id:
            return self.parts_by_id[uid]
        key = name.strip().lower()
        p = self.parts_by_name.get(key)
        if p is None:
            p = Part(name=name.strip()[:255], stock_qty=0, min_stock=0, sell_price=sell_price)
            self.db.add(p)
            await self.db.flush()
            self.parts_by_id[p.id] = p
            self.parts_by_name[key] = p
        return p


def _rows(tables: dict, name: str) -> list[dict]:
    rows = tables.get(name)
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


async def _wipe_repair_data(db: AsyncSession) -> None:
    """Режим «заменить»: удалить клиентов, ремонты со всем содержимым и склад разбора."""
    # Уведомления и очередь печати не трогаем — только отвязываем от ремонтов,
    # чтобы агент печати не потерял задания, а сотрудники — колокольчик.
    await db.execute(update(Notification).values(repair_id=None))
    await db.execute(update(PrintJob).values(repair_id=None))
    for model in (
        RepairEvent, RepairMaster, RepairPart, RepairPartOrder, Payment, RepairPhoto,
        Repair, Client, DonorPart, DonorUnit,
    ):
        await db.execute(delete(model))
    await db.flush()


async def import_payload(
    db: AsyncSession,
    payload: dict,
    *,
    actor: User,
    mode: str = "merge",
    media: dict[str, bytes] | None = None,
    source_meta: dict | None = None,
) -> ImportReport:
    """Загрузить данные файла обмена в БД. Всё — в одной транзакции.

    `mode`: merge — добавить/обновить; replace — предварительно очистить
    клиентов, ремонты (и всё привязанное) и склад разбора.
    """
    mode = "replace" if mode == "replace" else "merge"
    report = ImportReport(mode=mode, source_meta=source_meta or {})
    tables = payload.get("tables") or {}
    if not isinstance(tables, dict):
        report.error = "В файле нет раздела tables"
        return report

    ctx = _Ctx(db, actor, report)
    try:
        if mode == "replace":
            await _wipe_repair_data(db)
        await ctx.load()

        await _import_cities(ctx, _rows(tables, "cities"))
        await _import_branches(ctx, _rows(tables, "branches"))
        await _import_users(ctx, _rows(tables, "users"))
        await _import_clients(ctx, _rows(tables, "clients"))
        await _import_parts(ctx, _rows(tables, "parts"))
        await _import_prices(ctx, _rows(tables, "price_items"))
        await _import_equipment(ctx, _rows(tables, "equipment"))
        await _import_repairs(ctx, _rows(tables, "repairs"))
        await _import_repair_masters(ctx, _rows(tables, "repair_masters"))
        await _import_repair_parts(ctx, _rows(tables, "repair_parts"))
        await _import_part_orders(ctx, _rows(tables, "repair_part_orders"))
        await _import_payments(ctx, _rows(tables, "payments"))
        await _import_history(ctx, _rows(tables, "repair_history"))
        await _import_sms_log(ctx, _rows(tables, "sms_log"))
        await _import_print_log(ctx, _rows(tables, "print_log"))
        await _import_aliases(ctx, _rows(tables, "repair_number_aliases"))
        await _import_donors(ctx, _rows(tables, "donor_units"))
        await _import_donor_parts(ctx, _rows(tables, "donor_parts"))
        await _import_settings(ctx, _rows(tables, "app_settings"))
        report.media_restored = await _restore_media(media or {})
        await _import_photos(ctx, _rows(tables, "repairs"))
        await db.commit()
    except ImportError_ as e:
        await db.rollback()
        report.error = str(e)
    except Exception as e:  # noqa: BLE001 — любая ошибка = откат целиком
        await db.rollback()
        log.exception("Импорт данных прерван")
        report.error = f"Импорт прерван, изменения отменены: {type(e).__name__}: {e}"
    return report


# --- справочники -----------------------------------------------------------
async def _import_cities(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("cities")
    for rec in rows:
        slug = _s(rec.get("slug"), 16)
        if not slug:
            st.skipped += 1
            continue
        city = ctx.cities_by_slug.get(slug.lower())
        if city is None:
            uid = _uuid(rec.get("id"))
            city = City(
                id=uid if uid and uid not in ctx.cities_by_id else uuid.uuid4(),
                slug=slug.lower(), name=_s(rec.get("name"), 255) or slug.upper(),
                timezone=_s(rec.get("timezone"), 64) or "Asia/Ashgabat",
            )
            ctx.db.add(city)
            await ctx.db.flush()
            ctx.cities_by_id[city.id] = city
            ctx.cities_by_slug[slug.lower()] = city
            if ctx.default_city is None:
                ctx.default_city = city
            st.created += 1
        else:
            if _s(rec.get("name")):
                city.name = _s(rec.get("name"), 255)
            st.updated += 1
        if rec.get("id") is not None:
            ctx.city_refs[str(rec["id"])] = city


async def _import_branches(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("branches")
    for rec in rows:
        name = _s(rec.get("name"), 255)
        if not name:
            st.skipped += 1
            continue
        city = ctx.city_by_ref(rec.get("city_id"), rec.get("city_slug")) or await ctx.ensure_default_city()
        branch = ctx.branch_by_ref(rec.get("id"), name, city)
        if branch is None:
            uid = _uuid(rec.get("id"))
            branch = Branch(
                id=uid if uid and uid not in ctx.branches_by_id else uuid.uuid4(),
                city_id=city.id, name=name,
            )
            ctx.db.add(branch)
            st.created += 1
        else:
            st.updated += 1
        branch.address = _s(rec.get("address")) or branch.address
        branch.phone = _s(rec.get("phone"), 32) or branch.phone
        pc = jload(_first(rec, "print_config_json", "print_config"), None)
        if isinstance(pc, dict):
            branch.print_config = pc
        if "active" in rec:
            branch.active = _bool(rec.get("active"))
        await ctx.db.flush()
        ctx.branches_by_id[branch.id] = branch
        if rec.get("id") is not None:
            ctx.branch_refs[str(rec["id"])] = branch


async def _import_users(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("users")
    valid_roles = {r.value for r in UserRole}
    for rec in rows:
        email = _s(rec.get("email"), 255)
        name = _s(rec.get("name"), 255) or _s(rec.get("display_name"), 255)
        uid = _uuid(rec.get("id"))
        user = None
        if uid and uid in ctx.users_by_id:
            user = ctx.users_by_id[uid]
        elif email and email.lower() in ctx.users_by_email:
            user = ctx.users_by_email[email.lower()]
        if user is None and not (name or email):
            st.skipped += 1
            continue
        role = _s(rec.get("role"), 32)
        if role not in valid_roles:
            role = UserRole.OPERATOR.value
        extra_roles = [r for r in (jload(_first(rec, "extra_roles_json", "roles"), []) or []) if r in valid_roles]
        perms = [str(p) for p in (jload(_first(rec, "permissions_json", "permissions"), []) or [])]
        city = ctx.city_by_ref(rec.get("city_id"), rec.get("city_slug"))
        branch = ctx.branch_by_ref(rec.get("branch_id"), rec.get("branch_name"), city)
        is_actor = user is not None and user.id == ctx.actor.id
        if user is None:
            user = User(
                id=uid if uid and uid not in ctx.users_by_id else uuid.uuid4(),
                name=name or (email or "").split("@")[0],
                email=email or f"import-{secrets.token_hex(4)}@msb.local",
                password_hash=_s(rec.get("password_hash"), 255)
                or hash_password(secrets.token_urlsafe(24)),
                role=role,
                active=_bool(rec.get("active", 1)),
            )
            ctx.db.add(user)
            st.created += 1
            if not _s(rec.get("password_hash")):
                ctx.report.created_users.append(f"{user.name} ({role}, {user.email}) — пароль нужно задать заново")
        else:
            if name:
                user.name = name
            if not is_actor:
                # Самого себя импортом не «выключаем» и не понижаем в правах.
                user.role = role
                if "active" in rec:
                    user.active = _bool(rec.get("active"))
                if _s(rec.get("password_hash")):
                    user.password_hash = _s(rec.get("password_hash"), 255)
            st.updated += 1
        user.phone = _s(rec.get("phone"), 32) or user.phone
        user.telegram = _s(rec.get("telegram"), 128) or user.telegram
        if not is_actor:
            user.extra_roles = extra_roles
            user.extra_permissions = perms
        if city:
            user.city_id = city.id
        if branch:
            user.branch_id = branch.id
        created = parse_dt(rec.get("created_at"))
        if created:
            user.created_at = created
        await ctx.db.flush()
        ctx._index_user(user)
        if rec.get("id") is not None:
            ctx.user_refs[str(rec["id"])] = user


# --- клиенты ---------------------------------------------------------------
async def _import_clients(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("clients")
    if not rows:
        return
    existing = (await ctx.db.execute(select(Client))).scalars().all()
    by_id = {c.id: c for c in existing}
    by_norm = {c.phone_norm: c for c in existing}
    for rec in rows:
        phone = _s(_first(rec, "phone", "phone_raw"), 32) or ""
        norm = _s(rec.get("phone_norm"), 32) or normalize_phone(phone)
        if not norm:
            ctx.report.warn(f"Клиент «{_first(rec, 'full_name', 'name')}» без телефона пропущен")
            st.skipped += 1
            continue
        if not phone:
            phone = "+" + norm
        name = _s(_first(rec, "full_name", "name"), 255) or "Без имени"
        uid = _uuid(rec.get("id"))
        client = by_id.get(uid) if uid else None
        if client is None:
            client = by_norm.get(norm)
        if client is None:
            client = Client(
                id=uid if uid and uid not in by_id else uuid.uuid4(),
                full_name=name, phone=phone, phone_norm=norm,
            )
            ctx.db.add(client)
            st.created += 1
        else:
            client.full_name = name
            client.phone = phone
            st.updated += 1
        client.consent_pdn_at = parse_dt(rec.get("consent_pdn_at")) or client.consent_pdn_at
        client.consent_storage_at = parse_dt(rec.get("consent_storage_at")) or client.consent_storage_at
        if "deleted_at" in rec:
            client.deleted_at = parse_dt(rec.get("deleted_at"))
        created = parse_dt(rec.get("created_at"))
        if created:
            client.created_at = created
        updated = parse_dt(rec.get("updated_at"))
        if updated:
            client.updated_at = updated
        await ctx.db.flush()
        by_id[client.id] = client
        by_norm[norm] = client
        if rec.get("id") is not None:
            ctx.clients[str(rec["id"]).strip()] = client
        ctx.clients[str(client.id)] = client


# --- склад / прайс / купленная техника ------------------------------------
async def _import_parts(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("parts")
    if not rows:
        return
    by_sku = {p.sku: p for p in ctx.parts_by_id.values() if p.sku}
    for rec in rows:
        name = _s(rec.get("name"), 255)
        if not name:
            st.skipped += 1
            continue
        uid = _uuid(rec.get("id"))
        sku = _s(rec.get("sku"), 64)
        part = ctx.parts_by_id.get(uid) if uid else None
        if part is None and sku:
            part = by_sku.get(sku)
        if part is None:
            part = ctx.parts_by_name.get(name.lower())
        if part is None:
            part = Part(id=uid if uid and uid not in ctx.parts_by_id else uuid.uuid4(), name=name)
            ctx.db.add(part)
            st.created += 1
        else:
            part.name = name
            st.updated += 1
        if sku and by_sku.get(sku) in (None, part):
            part.sku = sku
        part.category = _s(rec.get("category"), 64) or part.category
        part.stock_qty = _int(rec.get("stock_qty"), part.stock_qty or 0)
        part.min_stock = _int(rec.get("min_stock"), part.min_stock or 0)
        part.cost_price = _money_in(rec, "cost_price") if ("cost_price_cents" in rec or "cost_price" in rec) else part.cost_price
        part.sell_price = _money_in(rec, "sell_price") if ("sell_price_cents" in rec or "sell_price" in rec) else part.sell_price
        part.supplier = _s(rec.get("supplier"), 255) or part.supplier
        if "active" in rec:
            part.active = _bool(rec.get("active"))
        created = parse_dt(rec.get("created_at"))
        if created:
            part.created_at = created
        await ctx.db.flush()
        ctx.parts_by_id[part.id] = part
        ctx.parts_by_name[name.lower()] = part
        if part.sku:
            by_sku[part.sku] = part


async def _import_prices(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("price_items")
    if not rows:
        return
    existing = (await ctx.db.execute(select(PriceItem))).scalars().all()
    by_id = {p.id: p for p in existing}

    def nkey(dt, brand, model, fault):
        return tuple((x or "").strip().lower() for x in (dt, brand, model, fault))

    by_key = {nkey(p.device_type, p.brand, p.model_or_line, p.fault): p for p in existing}
    for rec in rows:
        dt = _s(rec.get("device_type"), 32)
        brand = _s(rec.get("brand"), 128)
        model = _s(rec.get("model_or_line"), 128)
        fault = _s(rec.get("fault"), 255)
        if not any((dt, brand, model, fault)):
            st.skipped += 1
            continue
        uid = _uuid(rec.get("id"))
        item = by_id.get(uid) if uid else None
        if item is None:
            item = by_key.get(nkey(dt, brand, model, fault))
        if item is None:
            item = PriceItem(id=uid if uid and uid not in by_id else uuid.uuid4())
            ctx.db.add(item)
            st.created += 1
        else:
            st.updated += 1
        item.device_type, item.brand, item.model_or_line, item.fault = dt, brand, model, fault
        city = ctx.city_by_ref(rec.get("city_id"), rec.get("city_slug"))
        item.city_id = city.id if city else item.city_id
        item.price_min = _money_in(rec, "price_min")
        item.price_max = _money_in(rec, "price_max")
        item.price_avg = _money_in(rec, "price_avg")
        item.typical_days = _int(rec.get("typical_days"))
        item.source = _s(rec.get("source"), 32) or item.source
        item.active = _bool(rec.get("active", 1))
        created = parse_dt(rec.get("created_at"))
        if created:
            item.created_at = created
        await ctx.db.flush()
        by_id[item.id] = item
        by_key[nkey(dt, brand, model, fault)] = item


async def _import_equipment(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("equipment")
    if not rows:
        return
    existing = (await ctx.db.execute(select(Equipment))).scalars().all()
    by_id = {e.id: e for e in existing}
    by_key = {(e.name, e.brand, e.model, fmt_dt(e.purchased_at)): e for e in existing}
    for rec in rows:
        name = _s(rec.get("name"), 255)
        if not name:
            st.skipped += 1
            continue
        brand = _s(rec.get("brand"), 128)
        model = _s(rec.get("model"), 128)
        purchased = parse_dt(_first(rec, "purchased_at", "created_at"))
        uid = _uuid(rec.get("id"))
        eq = by_id.get(uid) if uid else None
        if eq is None:
            eq = by_key.get((name, brand, model, fmt_dt(purchased)))
        if eq is None:
            eq = Equipment(id=uid if uid and uid not in by_id else uuid.uuid4(), name=name)
            ctx.db.add(eq)
            st.created += 1
        else:
            st.updated += 1
        eq.name, eq.brand, eq.model = name, brand, model
        eq.purchase_price = _money_in(rec, "purchase_price")
        if purchased:
            eq.purchased_at = purchased
        eq.status = _s(rec.get("status"), 32) or eq.status or "in_stock"
        comps = jload(_first(rec, "components_json", "components"), None)
        if isinstance(comps, list):
            eq.components = [str(c) for c in comps]
        eq.storage_place = _s(rec.get("storage_place"), 255) or eq.storage_place
        eq.notes = _s(rec.get("notes")) or eq.notes
        eq.active = _bool(rec.get("active", 1))
        created = parse_dt(rec.get("created_at"))
        if created:
            eq.created_at = created
        await ctx.db.flush()
        by_id[eq.id] = eq
        by_key[(name, brand, model, fmt_dt(eq.purchased_at))] = eq


# --- ремонты ---------------------------------------------------------------
async def _import_repairs(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("repairs")
    if not rows:
        return
    existing = (
        await ctx.db.execute(select(Repair).options(selectinload(Repair.masters)))
    ).scalars().all()
    by_id = {r.id: r for r in existing}
    by_number = {r.number: r for r in existing}
    by_token = {r.public_token: r for r in existing}
    for r in existing:
        ctx.repairs[str(r.id)] = r
        ctx.repairs_by_number[r.number] = r

    for rec in rows:
        ref = rec.get("id")
        if parse_dt(rec.get("deleted_at")):
            st.skipped += 1
            continue
        client = ctx.client_by_ref(rec.get("client_id"))
        if client is None:
            # Клиент мог быть указан прямо в ремонте (упрощённая выгрузка).
            inline_phone = _s(_first(rec, "client_phone", "phone"), 32)
            if inline_phone:
                await _import_clients(
                    ctx,
                    [{
                        "id": rec.get("client_id"),
                        "full_name": _first(rec, "client_name", "client_full_name", default="Без имени"),
                        "phone": inline_phone,
                    }],
                )
                client = ctx.client_by_ref(rec.get("client_id"))
                if client is None:
                    norm = normalize_phone(inline_phone)
                    client = next((c for c in ctx.clients.values() if c.phone_norm == norm), None)
        if client is None:
            ctx.report.warn(f"Ремонт {rec.get('number') or ref}: клиент {rec.get('client_id')} не найден — пропущен")
            st.skipped += 1
            continue

        device_type = normalize_class(_s(_first(rec, "category", "device_type"), 32) or "Другое")
        uid = _uuid(ref)
        number = _s(rec.get("number"), 64)
        repair = by_id.get(uid) if uid else None
        if repair is None and number:
            repair = by_number.get(number)
        city = (
            ctx.city_by_ref(rec.get("city_id"), rec.get("city_slug"))
            or (ctx.cities_by_id.get(repair.city_id) if repair is not None else None)
            or await ctx.ensure_default_city()
        )
        branch = ctx.branch_by_ref(rec.get("branch_id"), rec.get("branch_name"), city)
        accepted_by = await ctx.user_by_ref(
            rec.get("accepted_by_id"), rec.get("accepted_by_name"), create_role=UserRole.OPERATOR.value
        ) or ctx.actor

        if repair is None:
            if not number:
                number = await next_repair_number(ctx.db, city.slug, device_type)
            token = _s(rec.get("public_token"), 64)
            if not token or token in by_token:
                token = new_public_token()
            repair = Repair(
                id=uid if uid and uid not in by_id else uuid.uuid4(),
                number=number,
                public_token=token,
                city_id=city.id,
                branch_id=branch.id if branch else None,
                client_id=client.id,
                device_type=device_type,
                accepted_by=accepted_by.id,
                status=RepairStatus.NEW,
                # Пустой список сразу: иначе первое обращение к коллекции после
                # flush уйдёт в ленивую загрузку, которой в async-сессии нет.
                masters=[],
            )
            ctx.db.add(repair)
            st.created += 1
        else:
            repair.client_id = client.id
            repair.device_type = device_type
            if branch:
                repair.branch_id = branch.id
            st.updated += 1

        repair.brand = _s(rec.get("brand"), 128)
        repair.model = _s(rec.get("model"), 128)
        repair.serial = _s(_first(rec, "serial_number", "serial"), 128)
        repair.fault_client = _s(rec.get("fault_client"))
        repair.fault_master = _s(_first(rec, "diagnosis", "fault_master"))
        repair.work_done = _s(rec.get("work_done"))
        repair.complectation = equipment_in(rec)
        repair.condition_notes = condition_in(rec)
        repair.is_delivery = _bool(rec.get("is_delivery"))
        repair.delivery_district = _s(rec.get("delivery_district"), 255)
        comment = _s(rec.get("delivery_comment"))
        person = _s(rec.get("delivery_person"))
        if person and (not comment or person not in comment):
            comment = f"{comment}; {person}" if comment else person
        repair.delivery_comment = comment
        repair.delivery_courier_phone = _s(_first(rec, "delivery_phone", "delivery_courier_phone"), 32)

        status = map_status(_s(rec.get("status"), 64)) or RepairStatus.NEW
        raw_status = _s(rec.get("status"), 64)
        repair.status = status
        repair.price_min = _money_in(rec, "price_min")
        repair.price_max = _money_in(rec, "price_max")
        repair.price_final = _money_in(rec, "price_final")
        repair.cost_amount = _money_in(rec, "cost") if ("cost_cents" in rec or "cost" in rec) else _money_in(rec, "cost_amount")
        repair.master_payout = _money_in(rec, "master_payout")
        repair.paid = _bool(_first(rec, "payment_mark", "paid", default=0))
        repair.eta_days = _int(rec.get("eta_days"))
        repair.eta_source = _s(rec.get("eta_source"), 16)
        repair.source = _s(rec.get("source"), 16) or repair.source or "walkin"
        repair.print_count = _int(rec.get("print_count"), repair.print_count or 0)
        repair.contact2_name = _s(rec.get("contact2_name"), 255)
        repair.contact2_phone = _s(rec.get("contact2_phone"), 32)
        repair.contact2_relation = _s(rec.get("contact2_relation"), 128)
        repair.consent_repair_at = parse_dt(rec.get("consent_repair_at"))

        warranty = _s(rec.get("warranty_text"), 64)
        w_start = parse_date(rec.get("warranty_start"))
        w_until = parse_date(rec.get("warranty_until"))
        if not warranty and w_until:
            base = w_start or (parse_dt(_first(rec, "finished_at", "issued_at")) or _utcnow()).date()
            days = (w_until - base).days
            if days > 0:
                warranty = f"{days} дней"
        repair.warranty_text = warranty

        created = parse_dt(rec.get("created_at"))
        accepted = parse_dt(rec.get("accepted_at")) or created
        if accepted:
            repair.accepted_at = accepted
        if created:
            repair.created_at = created
        updated = parse_dt(rec.get("updated_at"))
        if updated:
            repair.updated_at = updated
        repair.ready_at = parse_dt(_first(rec, "finished_at", "ready_at"))
        repair.issued_at = parse_dt(rec.get("issued_at"))
        repair.storage_until = parse_dt(rec.get("storage_until"))
        if repair.status == RepairStatus.DONE and repair.ready_at is None:
            repair.ready_at = repair.issued_at or updated or accepted or _utcnow()
        if raw_status in LEGACY_ISSUED_STATUSES and repair.issued_at is None:
            repair.issued_at = updated or repair.ready_at or _utcnow()

        master = await ctx.user_by_ref(
            _first(rec, "responsible_master_id", "master_id"),
            _first(rec, "responsible_master_name", "master_name"),
            create_role=UserRole.MASTER.value,
        )
        if master is not None:
            repair.master_id = master.id

        paid = rec.get("paid_cents")
        if paid not in (None, ""):
            ctx.paid_hint[repair.id] = _int(paid, 0) or 0

        await ctx.db.flush()
        by_id[repair.id] = repair
        by_number[repair.number] = repair
        by_token[repair.public_token] = repair
        if ref is not None:
            ctx.repairs[str(ref).strip()] = repair
        ctx.repairs[str(repair.id)] = repair
        ctx.repairs_by_number[repair.number] = repair


async def _import_repair_masters(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("repair_masters")
    touched: dict[uuid.UUID, Repair] = {}
    rewards: dict[uuid.UUID, int] = {}
    for rec in rows:
        repair = ctx.repair_by_ref(rec.get("repair_id"))
        if repair is None:
            ctx.report.warn(f"Мастер на ремонте: ремонт {rec.get('repair_id')} не найден")
            st.skipped += 1
            continue
        user = await ctx.user_by_ref(
            rec.get("user_id"), _first(rec, "display_name", "name"), create_role=UserRole.MASTER.value
        )
        if user is None:
            ctx.report.warn(f"Ремонт {repair.number}: сотрудник {rec.get('user_id')} не найден")
            st.skipped += 1
            continue
        role = (_s(rec.get("assignment_role")) or _s(rec.get("kind")) or "master").lower()
        kind = "helper" if role in ("assistant", "helper", "помощник") else "master"
        link = next((m for m in repair.masters if m.user_id == user.id), None)
        if link is None:
            link = RepairMaster(repair_id=repair.id, user_id=user.id, kind=kind)
            repair.masters.append(link)
            st.created += 1
        else:
            link.kind = kind
            st.updated += 1
        pos = _int(rec.get("position"))
        if pos is not None:
            link.position = pos
        if kind == "master" and repair.master_id is None:
            repair.master_id = user.id
        rewards[repair.id] = rewards.get(repair.id, 0) + (_int(rec.get("reward_cents"), 0) or 0)
        touched[repair.id] = repair
    for rid, repair in touched.items():
        masters = [m for m in repair.masters if (m.kind or "master") != "helper"]
        helpers = [m for m in repair.masters if (m.kind or "master") == "helper"]
        for i, m in enumerate(sorted(masters, key=lambda x: (x.position or 0))):
            m.position = i
        for i, m in enumerate(sorted(helpers, key=lambda x: (x.position or 0)), start=len(masters)):
            m.position = i
        if repair.master_payout is None and rewards.get(rid):
            repair.master_payout = from_cents(rewards[rid])
    # Ремонты, у которых указан ответственный мастер, но нет строки в repair_masters.
    for repair in {id(r): r for r in ctx.repairs.values()}.values():
        if repair.master_id and not any(m.user_id == repair.master_id for m in repair.masters):
            repair.masters.append(RepairMaster(repair_id=repair.id, user_id=repair.master_id, position=0, kind="master"))
    await ctx.db.flush()


async def _import_repair_parts(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("repair_parts")
    if not rows:
        return
    existing = (await ctx.db.execute(select(RepairPart))).scalars().all()
    by_id = {rp.id: rp for rp in existing}
    by_pair = {(rp.repair_id, rp.part_id): rp for rp in existing}
    for rec in rows:
        repair = ctx.repair_by_ref(rec.get("repair_id"))
        name = _s(rec.get("name"), 255)
        if repair is None or not name:
            st.skipped += 1
            continue
        price = _money_in(rec, "unit_cost") if ("unit_cost_cents" in rec or "unit_cost" in rec) else _money_in(rec, "price")
        part = await ctx.part_by_name(name, part_ref=rec.get("part_id"), sell_price=price)
        uid = _uuid(rec.get("id"))
        rp = by_id.get(uid) if uid else None
        if rp is None:
            rp = by_pair.get((repair.id, part.id))
        qty = max(1, _int(_first(rec, "quantity", "qty"), 1) or 1)
        if rp is None:
            rp = RepairPart(
                id=uid if uid and uid not in by_id else uuid.uuid4(),
                repair_id=repair.id, part_id=part.id, qty=qty, price=price,
                is_manual=_bool(rec.get("is_manual", 1)),
            )
            ctx.db.add(rp)
            st.created += 1
        else:
            rp.qty = qty
            rp.price = price
            st.updated += 1
        created = parse_dt(rec.get("created_at"))
        if created:
            rp.created_at = created
        await ctx.db.flush()
        by_id[rp.id] = rp
        by_pair[(repair.id, part.id)] = rp


async def _import_part_orders(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("repair_part_orders")
    if not rows:
        return
    existing = (await ctx.db.execute(select(RepairPartOrder))).scalars().all()
    by_id = {o.id: o for o in existing}
    by_key = {(o.repair_id, o.name, fmt_dt(o.created_at)): o for o in existing}
    for rec in rows:
        repair = ctx.repair_by_ref(rec.get("repair_id"))
        name = _s(rec.get("name"), 255)
        if repair is None or not name:
            st.skipped += 1
            continue
        created = parse_dt(rec.get("created_at"))
        uid = _uuid(rec.get("id"))
        order = by_id.get(uid) if uid else None
        if order is None:
            order = by_key.get((repair.id, name, fmt_dt(created)))
        if order is None:
            order = RepairPartOrder(id=uid if uid and uid not in by_id else uuid.uuid4(), repair_id=repair.id, name=name)
            ctx.db.add(order)
            st.created += 1
        else:
            st.updated += 1
        order.qty = max(1, _int(_first(rec, "quantity", "qty"), 1) or 1)
        order.price = _money_in(rec, "price")
        order.ordered_at = parse_dt(rec.get("ordered_at"))
        order.received_at = parse_dt(rec.get("received_at"))
        creator = await ctx.user_by_ref(_first(rec, "created_by_id", "created_by"), rec.get("created_by_name"))
        order.created_by = creator.id if creator else None
        if created:
            order.created_at = created
        await ctx.db.flush()
        by_id[order.id] = order
        by_key[(repair.id, name, fmt_dt(order.created_at))] = order


async def _import_payments(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("payments")
    existing = (await ctx.db.execute(select(Payment))).scalars().all()
    by_id = {p.id: p for p in existing}
    by_key = {(p.repair_id, to_cents(p.amount), fmt_dt(p.paid_at)): p for p in existing}
    has_payments = {p.repair_id for p in existing}
    for rec in rows:
        repair = ctx.repair_by_ref(rec.get("repair_id"))
        amount = _money_in(rec, "amount")
        if repair is None or amount is None:
            st.skipped += 1
            continue
        paid_at = parse_dt(_first(rec, "paid_at", "created_at")) or _utcnow()
        uid = _uuid(rec.get("id"))
        payment = by_id.get(uid) if uid else None
        if payment is None:
            payment = by_key.get((repair.id, to_cents(amount), fmt_dt(paid_at)))
        method = (_s(rec.get("method"), 16) or "cash").lower()
        if method not in ("cash", "card", "transfer"):
            method = "cash"
        operator = await ctx.user_by_ref(rec.get("operator_id"), rec.get("operator_name"))
        if payment is None:
            payment = Payment(
                id=uid if uid and uid not in by_id else uuid.uuid4(),
                repair_id=repair.id, amount=amount, method=method, paid_at=paid_at,
                operator_id=operator.id if operator else None,
            )
            ctx.db.add(payment)
            st.created += 1
        else:
            payment.amount = amount
            payment.method = method
            st.updated += 1
        await ctx.db.flush()
        by_id[payment.id] = payment
        by_key[(repair.id, to_cents(amount), fmt_dt(paid_at))] = payment
        has_payments.add(repair.id)
    # Старая база хранила только сумму «оплачено»: превращаем её в один платёж.
    for rid, cents in ctx.paid_hint.items():
        if cents > 0 and rid not in has_payments:
            repair = ctx.repairs.get(str(rid))
            paid_at = (repair.issued_at or repair.ready_at or repair.accepted_at) if repair else _utcnow()
            ctx.db.add(Payment(repair_id=rid, amount=from_cents(cents), method="cash", paid_at=paid_at or _utcnow()))
            st.created += 1
            has_payments.add(rid)
    await ctx.db.flush()


async def _add_event(ctx: _Ctx, repair: Repair, etype: str, created_at, data: dict, actor_id, uid: uuid.UUID | None) -> bool:
    """Добавить событие в историю, если такого ещё нет. True — создано."""
    key = ctx._event_key(etype, created_at, data)
    keys = ctx.event_keys.setdefault(repair.id, set())
    if uid:
        # Наш собственный экспорт: UUID — надёжный признак «то же событие».
        if uid in ctx.event_ids:
            return False
    elif key in keys:
        return False
    ev = RepairEvent(
        id=uid if uid else uuid.uuid4(),
        repair_id=repair.id, type=etype[:32], actor_id=actor_id, data=data,
    )
    if created_at:
        ev.created_at = created_at
        ev.updated_at = created_at
    ctx.db.add(ev)
    keys.add(key)
    ctx.event_ids.add(ev.id)
    return True


async def _import_history(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("repair_history")
    if not rows:
        return
    repairs = [ctx.repair_by_ref(r.get("repair_id")) for r in rows]
    await ctx.preload_events(list({r.id for r in repairs if r}))
    for rec, repair in zip(rows, repairs):
        if repair is None:
            st.skipped += 1
            continue
        etype = _s(_first(rec, "event_type", "type"), 32) or "comment"
        details = jload(_first(rec, "details_json", "data", "details"), {})
        data = dict(details) if isinstance(details, dict) else {"details": details}
        comment = _s(rec.get("comment"))
        if comment and not data.get("message"):
            if etype == "status_change" and "→" in comment and not data.get("to"):
                left, _, right = comment.partition("→")
                data.setdefault("from", left.strip() or None)
                data.setdefault("to", right.strip() or None)
            else:
                data["message"] = comment
        actor = await ctx.user_by_ref(_first(rec, "actor_user_id", "actor_id"), rec.get("actor_name"))
        uid = _uuid(rec.get("id"))
        if rec.get("id") is not None:
            ctx.history_ids.add(str(rec["id"]))
        created = parse_dt(rec.get("created_at"))
        if await _add_event(ctx, repair, etype, created, data, actor.id if actor else None, uid):
            st.created += 1
        else:
            st.skipped += 1
    await ctx.db.flush()


async def _import_sms_log(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("sms_log")
    if not rows:
        return
    repairs = [ctx.repair_by_ref(r.get("repair_id")) for r in rows]
    await ctx.preload_events(list({r.id for r in repairs if r}))
    for rec, repair in zip(rows, repairs):
        if repair is None:
            st.skipped += 1
            continue
        if rec.get("id") is not None and str(rec["id"]) in ctx.history_ids:
            st.skipped += 1  # уже загружено как событие истории
            continue
        text = _s(rec.get("text")) or ""
        status = (_s(rec.get("status")) or "sent").lower()
        ok = status in ("sent", "ok", "delivered", "1", "true")
        data = {
            "message": text if ok else f"SMS не отправлено: {_s(rec.get('detail')) or status}",
            "kind": _s(rec.get("kind")) or "sms",
            "sms_text": text,
            "phone": _s(rec.get("phone"), 32),
            "ok": ok,
        }
        actor = await ctx.user_by_ref(_first(rec, "actor_user_id", "actor_id"), rec.get("actor_name"))
        created = parse_dt(_first(rec, "created_at", "sent_at"))
        if await _add_event(ctx, repair, "notify", created, data, actor.id if actor else None, _uuid(rec.get("id"))):
            st.created += 1
        else:
            st.skipped += 1
    await ctx.db.flush()


async def _import_print_log(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("print_log")
    if not rows:
        return
    existing = (await ctx.db.execute(select(PrintJob))).scalars().all()
    by_id = {j.id: j for j in existing}
    by_key = {(j.repair_id, fmt_dt(j.created_at)): j for j in existing}
    for rec in rows:
        repair = ctx.repair_by_ref(rec.get("repair_id"))
        created = parse_dt(rec.get("created_at"))
        uid = _uuid(rec.get("id"))
        job = by_id.get(uid) if uid else None
        if job is None and repair is not None:
            job = by_key.get((repair.id, fmt_dt(created)))
        if job is not None:
            st.skipped += 1
            continue
        status = (_s(rec.get("status"), 16) or "done").lower()
        error = _s(rec.get("error"))
        if status in ("queued", "sent"):
            # Без PDF задание печатать нечем: агент печати опрашивает очередь.
            status, error = "failed", error or "Импорт: задание восстановлено без PDF"
        job = PrintJob(
            id=uid if uid and uid not in by_id else uuid.uuid4(),
            repair_id=repair.id if repair else None,
            template_id=_s(rec.get("template_id"), 64),
            payload={"imported": True, "kind": _s(rec.get("kind")) or "blank"},
            status=status,
            attempts=_int(rec.get("attempts"), 0) or 0,
            error=error,
            branch_id=repair.branch_id if repair else None,
            sent_at=parse_dt(rec.get("sent_at")),
        )
        if created:
            job.created_at = created
        ctx.db.add(job)
        st.created += 1
        await ctx.db.flush()
        by_id[job.id] = job


async def _import_aliases(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("repair_number_aliases")
    if not rows:
        return
    setting = (await ctx.db.execute(select(Setting).where(Setting.key == ALIASES_KEY))).scalar_one_or_none()
    items: dict = dict(((setting.value or {}).get("items") or {}) if setting else {})
    for rec in rows:
        old = _s(rec.get("old_number"), 64)
        repair = ctx.repair_by_ref(rec.get("repair_id"))
        if not old or repair is None:
            st.skipped += 1
            continue
        if items.get(old) == str(repair.id):
            st.skipped += 1
            continue
        st.updated += 1 if old in items else 0
        st.created += 0 if old in items else 1
        items[old] = str(repair.id)
    if setting is None:
        setting = Setting(key=ALIASES_KEY, value={"items": items},
                          description="Старые номера ремонтов → id (импорт из прежней базы)")
        ctx.db.add(setting)
    else:
        setting.value = {"items": items}
    await ctx.db.flush()


async def _import_donors(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("donor_units")
    if not rows:
        return
    existing = (await ctx.db.execute(select(DonorUnit))).scalars().all()
    by_id = {d.id: d for d in existing}
    by_key = {(d.brand, d.model, fmt_dt(d.created_at)): d for d in existing}
    for d in existing:
        ctx.donors[str(d.id)] = d
    for rec in rows:
        brand = _s(rec.get("brand"), 128)
        if not brand:
            st.skipped += 1
            continue
        model = _s(rec.get("model"), 128) or ""
        created = parse_dt(rec.get("created_at"))
        uid = _uuid(rec.get("id"))
        donor = by_id.get(uid) if uid else None
        if donor is None:
            donor = by_key.get((brand, model, fmt_dt(created)))
        comment = _s(rec.get("comment"))
        extras = []
        if _s(rec.get("serial_number")):
            extras.append(f"S/N: {_s(rec.get('serial_number'))}")
        if _s(rec.get("board_number")):
            extras.append(f"Плата: {_s(rec.get('board_number'))}")
        for x in extras:
            if not comment or x not in comment:
                comment = f"{comment}; {x}" if comment else x
        creator = await ctx.user_by_ref(rec.get("created_by_id"), rec.get("created_by_name"))
        if donor is None:
            donor = DonorUnit(id=uid if uid and uid not in by_id else uuid.uuid4(), brand=brand, model=model)
            ctx.db.add(donor)
            st.created += 1
        else:
            donor.brand, donor.model = brand, model
            st.updated += 1
        donor.comment = comment
        if creator:
            donor.created_by_id = creator.id
        if created:
            donor.created_at = created
        updated = parse_dt(rec.get("updated_at"))
        if updated:
            donor.updated_at = updated
        await ctx.db.flush()
        by_id[donor.id] = donor
        by_key[(brand, model, fmt_dt(donor.created_at))] = donor
        if rec.get("id") is not None:
            ctx.donors[str(rec["id"]).strip()] = donor
        ctx.donors[str(donor.id)] = donor


async def _import_donor_parts(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("donor_parts")
    if not rows:
        return
    existing = (await ctx.db.execute(select(DonorPart))).scalars().all()
    by_id = {p.id: p for p in existing}
    by_key = {(p.donor_id, p.name, p.panel_number or ""): p for p in existing}
    for rec in rows:
        donor = ctx.donors.get(str(rec.get("donor_id") or "").strip())
        name = _s(rec.get("name"), 255)
        if donor is None or not name:
            st.skipped += 1
            continue
        panel = _s(rec.get("panel_number"), 128)
        uid = _uuid(rec.get("id"))
        part = by_id.get(uid) if uid else None
        if part is None:
            part = by_key.get((donor.id, name, panel or ""))
        comment = _s(rec.get("comment"))
        qty = _int(_first(rec, "quantity", "qty"), 1) or 1
        if qty > 1:
            note = f"Кол-во: {qty}"
            if not comment or note not in comment:
                comment = f"{comment}; {note}" if comment else note
        if part is None:
            part = DonorPart(id=uid if uid and uid not in by_id else uuid.uuid4(), donor_id=donor.id, name=name)
            ctx.db.add(part)
            st.created += 1
        else:
            part.name = name
            st.updated += 1
        part.panel_number = panel
        part.price_sale = _money_in(rec, "price") if ("price_cents" in rec or "price" in rec) else _money_in(rec, "price_sale")
        part.comment = comment
        created = parse_dt(rec.get("created_at"))
        if created:
            part.created_at = created
        await ctx.db.flush()
        by_id[part.id] = part
        by_key[(donor.id, name, panel or "")] = part


async def _import_settings(ctx: _Ctx, rows: list[dict]) -> None:
    st = ctx.report.stat("app_settings")
    if not rows:
        return
    existing = {s.key: s for s in (await ctx.db.execute(select(Setting))).scalars().all()}
    for rec in rows:
        key = _s(rec.get("key"), 128)
        if not key:
            st.skipped += 1
            continue
        if key in PROTECTED_SETTINGS or key == ALIASES_KEY:
            st.skipped += 1
            continue
        value = jload(_first(rec, "value_json", "value"), None)
        if not isinstance(value, dict):
            # Setting.value — словарь; скалярные значения старой базы оборачиваем.
            value = {"value": value}
        setting = existing.get(key)
        if setting is None:
            setting = Setting(key=key, value=value, description=_s(rec.get("description")))
            ctx.db.add(setting)
            existing[key] = setting
            st.created += 1
        else:
            setting.value = value
            if _s(rec.get("description")):
                setting.description = _s(rec.get("description"))
            st.updated += 1
    await ctx.db.flush()


async def _restore_media(media: dict[str, bytes]) -> int:
    if not media or app_settings.STORAGE_MODE != "local":
        return 0
    root = Path(app_settings.UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    restored = 0
    for key, data in media.items():
        target = _safe_media_path(root, key)
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored += 1
    return restored


async def _import_photos(ctx: _Ctx, rows: list[dict]) -> None:
    """Записи о фото создаются только когда сам файл есть в хранилище."""
    st = ctx.report.stat("repair_photos")
    root = Path(app_settings.UPLOAD_DIR)
    existing_keys: set[str] | None = None
    missing = 0
    for rec in rows:
        photos = jload(rec.get("photos_json"), []) or []
        if not photos:
            continue
        repair = ctx.repair_by_ref(rec.get("id"))
        if repair is None:
            continue
        if existing_keys is None:
            existing_keys = set(
                (await ctx.db.execute(select(RepairPhoto.object_key))).scalars().all()
            )
        for ph in photos:
            key = ph.get("object_key") if isinstance(ph, dict) else str(ph)
            if not key:
                continue
            if key in existing_keys:
                st.skipped += 1
                continue
            path = _safe_media_path(root, key) if app_settings.STORAGE_MODE == "local" else None
            if path is None or not path.is_file():
                missing += 1
                st.skipped += 1
                continue
            thumb = ph.get("thumb_key") if isinstance(ph, dict) else None
            thumb_path = _safe_media_path(root, thumb) if thumb else None
            photo = RepairPhoto(
                id=_uuid(ph.get("id")) if isinstance(ph, dict) and _uuid(ph.get("id")) else uuid.uuid4(),
                repair_id=repair.id,
                object_key=key,
                thumb_key=thumb if (thumb_path and thumb_path.is_file()) else None,
                caption=_s(ph.get("caption"), 255) if isinstance(ph, dict) else None,
            )
            created = parse_dt(ph.get("created_at")) if isinstance(ph, dict) else None
            if created:
                photo.created_at = created
            ctx.db.add(photo)
            existing_keys.add(key)
            st.created += 1
    if missing:
        ctx.report.warn(
            f"Фотографии: {missing} файл(ов) нет в хранилище — записи пропущены "
            f"(выгружайте архив с фотографиями, чтобы восстановить их)."
        )
    await ctx.db.flush()


# ==========================================================================
# Псевдонимы номеров (используются поиском по номеру)
# ==========================================================================
async def resolve_alias(db: AsyncSession, number: str) -> uuid.UUID | None:
    """Старый номер ремонта (из прежней базы) → id ремонта в MSB."""
    if not number:
        return None
    setting = (await db.execute(select(Setting).where(Setting.key == ALIASES_KEY))).scalar_one_or_none()
    items = (setting.value or {}).get("items") if setting else None
    if not isinstance(items, dict):
        return None
    return _uuid(items.get(number.strip()))
