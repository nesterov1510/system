"""Repair number generation + client phone normalisation.

Number format: `{TYPE}-{CITY}-{YYYY}-{NNNNN}` (пример: `TV-ASG-2026-01482`).

Регион развёртывания — Туркменистан (+993), поэтому нормализация телефона
приводит номер к каноническому виду `993XXXXXXXX` (11 цифр). Это ОБЯЗАНО
совпадать с `apps/web/lib/phone.ts`, иначе один и тот же человек, записанный
в разных форматах, превращается в нескольких клиентов.
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Repair

# Типы техники из справочника UI (apps/web/lib/catalog.ts -> DEVICE_CLASSES).
# Ключи ОБЯЗАНЫ совпадать со значениями, которые фронтенд шлёт в device_type,
# иначе все номера деградируют в общий префикс "RE".
DEVICE_PREFIX = {
    "Телевизоры": "TV",
    "Компьютеры": "PC",
    "Бытовая техника": "BT",
    "Другое": "OT",
    # Legacy-значения (ремонт может быть принят до смены справочника).
    "ТВ": "TV",
    "Монитор": "MN",
    "Аудио": "AU",
    "Компьютер": "PC",
    "Ноутбук": "PC",
    "Бытовая": "BT",
}

# Префикс для неизвестного типа техники.
FALLBACK_PREFIX = "RE"

# Код страны по умолчанию (Туркменистан).
DEFAULT_COUNTRY_CODE = "993"


def device_prefix(device_type: str) -> str:
    return DEVICE_PREFIX.get((device_type or "").strip(), FALLBACK_PREFIX)


async def next_repair_number(db: AsyncSession, city_slug: str, device_type: str) -> str:
    """Сгенерировать человекочитаемый последовательный номер по (город, год).

    Счётчик читает максимальный существующий номер и увеличивает его. При
    одновременной приёмке двумя операторами возможна гонка — поэтому вызывающий
    код обязан повторить попытку при `IntegrityError` (см. `_persist_repair` и
    `create_repair` в `app.routers.repairs`).

    Город приходит строкой (`city.slug`), а не ORM-объектом: приёмка повторяет
    попытку после `rollback()`, который «протухает» (expire) все объекты
    сессии, и ленивое чтение атрибута города в async-коде падало с
    `MissingGreenlet` — то есть честный повтор номера не работал вовсе.
    """
    prefix = device_prefix(device_type)
    city_slug = (city_slug or "").upper()
    year = datetime.now(timezone.utc).year

    pattern = f"{prefix}-{city_slug}-{year}-%"
    row = await db.execute(
        select(func.max(Repair.number)).where(Repair.number.like(pattern))
    )
    max_number = row.scalar_one_or_none()

    seq = 1
    if max_number:
        try:
            seq = int(max_number.rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1

    return f"{prefix}-{city_slug}-{year}-{seq:05d}"


def new_public_token() -> str:
    """128-bit cryptographically random, URL-safe, non-enumerable token."""
    return secrets.token_urlsafe(24)  # 24 bytes = 192 bits, >128


def phone_digits(phone: str) -> str:
    """Только цифры номера (без '+', пробелов и скобок)."""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def normalize_phone(phone: str) -> str:
    """Привести телефон к каноническому виду для уникального индекса `phone_norm`.

    Туркменские номера (регион развёртывания) всегда приводятся к
    `993XXXXXXXX` — 11 цифр:

    ==========================  ==================
    Ввод оператора              phone_norm
    ==========================  ==================
    ``+993 61 234567``          ``99361234567``
    ``8 61 234567``             ``99361234567``
    ``61 234567``               ``99361234567``
    ==========================  ==================

    Номера других стран не искажаются: если номер длиннее местного и не
    начинается с 993/8, он сохраняется как есть (с ведущим кодом страны).

    Пустая строка возвращается только если в телефоне вообще нет цифр —
    вызывающий код обязан это отклонить, иначе все такие клиенты сливаются
    в одну запись (phone_norm UNIQUE).
    """
    digits = phone_digits(phone)
    if not digits:
        return ""

    # Уже с туркменским кодом страны.
    if digits.startswith(DEFAULT_COUNTRY_CODE) and len(digits) == 11:
        return digits

    # Местный формат «8 XX XXXXXX» (9 цифр) — 8 это внутренний префикс,
    # заменяем его на код страны.
    if digits.startswith("8") and len(digits) == 9:
        return DEFAULT_COUNTRY_CODE + digits[1:]

    # Местный формат без префикса: «XX XXXXXX» (8 цифр).
    if len(digits) == 8:
        return DEFAULT_COUNTRY_CODE + digits

    # Прочие страны — не искажаем номер.
    return digits
