"""Statistics helpers (anonymized city stats for the public QR page).

Anti-hallucination rule: if the sample size is below the threshold, return
`{"message": "мало данных"}` and no invented numbers.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Repair

# Minimum sample size before we show aggregate numbers.
MIN_SAMPLE = 3


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def _resolved_price(r: Repair) -> float | None:
    for val in (r.price_final, r.price_max, r.price_min):
        if val is not None:
            return float(val)
    return None


async def city_stats(
    db: AsyncSession, city_id: uuid.UUID, device_type: str | None = None
) -> dict:
    q = select(Repair).where(
        Repair.city_id == city_id, Repair.ready_at.isnot(None)
    )
    if device_type:
        q = q.where(Repair.device_type == device_type)

    rows = (await db.execute(q)).scalars().all()
    n = len(rows)

    result: dict = {
        "n": n,
        "threshold": MIN_SAMPLE,
        "avg_days": None,
        "median_days": None,
        "avg_price": None,
        "message": None,
    }

    if n < MIN_SAMPLE:
        result["message"] = "мало данных"
        return result

    days = []
    prices = []
    for r in rows:
        dur = (r.ready_at - r.accepted_at).total_seconds() / 86400.0
        days.append(dur)
        p = _resolved_price(r)
        if p is not None:
            prices.append(p)

    if days:
        result["avg_days"] = round(sum(days) / len(days), 1)
        result["median_days"] = round(_median(days) or 0, 1)
    if prices:
        result["avg_price"] = int(round(sum(prices) / len(prices)))

    return result
