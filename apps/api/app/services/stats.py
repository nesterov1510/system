"""Dashboard statistics ("курс ремонта") — сроки/чеки по городу, типу,
бренду, мастеру. Anti-hallucination: below threshold -> "мало данных".
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Part, Payment, Repair

MIN_SAMPLE = 3


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, int(0.9 * len(s)))
    return s[idx]


def _resolved_price(r: Repair) -> float | None:
    for val in (r.price_final, r.price_max, r.price_min):
        if val is not None:
            return float(val)
    return None


async def city_stats(
    db: AsyncSession, city_id: uuid.UUID, device_type: str | None = None
) -> dict:
    """Anonymized city stats for the public QR page."""
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


async def overview(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    total = (await db.execute(select(func.count(Repair.id)))).scalar_one()
    active = (
        await db.execute(
            select(func.count(Repair.id)).where(
                Repair.status.notin_(["Выдано", "Отказ", "Архив"])
            )
        )
    ).scalar_one()
    overdue = (
        await db.execute(
            select(func.count(Repair.id)).where(
                Repair.storage_until.isnot(None),
                Repair.storage_until < now,
                Repair.status.notin_(["Выдано", "Отказ", "Архив"]),
            )
        )
    ).scalar_one()
    low_stock = (
        await db.execute(
            select(func.count(Part.id)).where(
                Part.active.is_(True), Part.stock_qty <= Part.min_stock
            )
        )
    ).scalar_one()
    revenue = (
        await db.execute(select(func.coalesce(func.sum(Payment.amount), 0)))
    ).scalar_one()
    revenue_30d = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.paid_at >= now - __import__("datetime").timedelta(days=30)
            )
        )
    ).scalar_one()

    # Прибыль по завершённым ремонтам: выручка (price_final) − расходы (cost_amount).
    fin = (
        await db.execute(
            select(
                func.count(Repair.id),
                func.coalesce(func.sum(Repair.price_final), 0),
                func.coalesce(func.sum(Repair.cost_amount), 0),
            ).where(Repair.price_final.isnot(None))
        )
    ).one()
    finished_count, finished_revenue, finished_cost = fin
    profit = float(finished_revenue or 0) - float(finished_cost or 0)

    return {
        "total": total,
        "active": active,
        "overdue_storage": overdue,
        "low_stock": low_stock,
        "revenue": float(revenue or 0),
        "revenue_30d": float(revenue_30d or 0),
        "finished_count": int(finished_count or 0),
        "finished_revenue": float(finished_revenue or 0),
        "finished_cost": float(finished_cost or 0),
        "profit": profit,
    }


async def _aggregate(db, filters: list, group_label: str) -> dict:
    q = select(Repair).where(Repair.ready_at.isnot(None), *filters)
    rows = (await db.execute(q)).scalars().all()
    n = len(rows)
    result: dict = {
        "group": group_label,
        "n": n,
        "threshold": MIN_SAMPLE,
        "avg_days": None,
        "median_days": None,
        "p90_days": None,
        "avg_price": None,
        "sla_pct": None,
        "message": None,
    }
    if n < MIN_SAMPLE:
        result["message"] = "мало данных"
        return result

    days = []
    prices = []
    in_sla = 0
    for r in rows:
        dur = (r.ready_at - r.accepted_at).total_seconds() / 86400.0
        days.append(dur)
        if r.eta_days is not None and dur <= r.eta_days:
            in_sla += 1
        p = _resolved_price(r)
        if p is not None:
            prices.append(p)

    if days:
        result["avg_days"] = round(sum(days) / len(days), 1)
        result["median_days"] = round(_median(days) or 0, 1)
        result["p90_days"] = round(_p90(days) or 0, 1)
        result["sla_pct"] = round(in_sla / len(days) * 100, 1)
    if prices:
        result["avg_price"] = int(round(sum(prices) / len(prices)))
    return result


async def tiles(
    db: AsyncSession,
    type_: str | None = None,
    brand: str | None = None,
    model: str | None = None,
    city_id: uuid.UUID | None = None,
) -> list[dict]:
    filters = []
    if type_:
        filters.append(Repair.device_type == type_)
    if brand:
        filters.append(Repair.brand == brand)
    if city_id:
        filters.append(Repair.city_id == city_id)

    out = []
    # Overall tile
    out.append(await _aggregate(db, filters, "Всего"))
    # By device type
    if not type_:
        row = await db.execute(select(Repair.device_type).distinct())
        for (dt,) in row.all():
            f = filters + [Repair.device_type == dt]
            out.append(await _aggregate(db, f, dt))
    # By master (if not filtering by brand/type, to keep it simple)
    if not brand and not type_:
        from app.db.models import User

        row = await db.execute(
            select(Repair.master_id).where(Repair.master_id.isnot(None)).distinct()
        )
        for (mid,) in row.all():
            u = await db.get(User, mid)
            f = filters + [Repair.master_id == mid]
            out.append(await _aggregate(db, f, u.name if u else str(mid)))
    return out
