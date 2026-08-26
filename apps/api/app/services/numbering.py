"""Repair number generation: `{TYPE}-{CITY}-{YYYY}-{NNNNN}`.

Example: TV-MSK-2026-01482.
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import City, Repair

DEVICE_PREFIX = {
    "ТВ": "TV",
    "Монитор": "MN",
    "Аудио": "AU",
    "Другое": "OT",
}


def device_prefix(device_type: str) -> str:
    return DEVICE_PREFIX.get(device_type, "RE")


async def next_repair_number(db: AsyncSession, city: City, device_type: str) -> str:
    """Generate a unique, human-readable sequential number per city/year.

    The counter is per (city, year). It reads the max existing sequence and
    increments it. For MVP concurrency this is acceptable; a dedicated
    sequence/table can be added later if two acceptances race.
    """
    prefix = device_prefix(device_type)
    city_slug = city.slug.upper()
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


def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    # Strip leading country code 8/7 -> canonical 10-digit Russian number.
    if digits.startswith("8") and len(digits) == 11:
        digits = digits[1:]
    elif digits.startswith("7") and len(digits) == 11:
        digits = digits[1:]
    return digits
