"""Dashboard statistics ("курс ремонта") — сроки/чеки по городу, типу,
бренду, мастеру. Anti-hallucination: below threshold -> "мало данных".
"""
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import Part, Payment, Repair

MIN_SAMPLE = 3
ASHGABAT = ZoneInfo("Asia/Ashgabat")

CLOSED_STATUSES = ("Выдано", "Архив", "Отказ")
IN_PROCESS_STATUSES = ("Принято", "Диагностика", "Согласование", "В ремонте")

DASHBOARD_FILTER_LABELS = {
    "all": "Все ремонты",
    "ready": "Готово к выдаче",
    "waiting-parts": "Ожидаем запчасть",
    "today": "Сегодня принята",
    "in-repair": "В процессе ремонта",
    "not-picked-up": "Не забирает",
    "disposable": "Можно выбрасывать",
    "warranty": "На гарантии",
}

PERIOD_LABELS = {
    "today": "Сегодня",
    "week": "Неделя",
    "14d": "14 дней",
    "month": "Месяц",
    "3m": "3 месяца",
    "6m": "6 месяцев",
    "year": "Год",
    "all": "Всё время",
    "custom": "Свой период",
}

_MONTHS_RU = (
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
)


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


def _today_start_utc() -> datetime:
    now_local = datetime.now(ASHGABAT)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc).replace(tzinfo=None)


def _to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ASHGABAT)


def dashboard_filter_clauses(key: str | None) -> list:
    """SQL-условия для карточек панели и списка ремонтов — одно и то же."""
    if not key or key == "all":
        return []
    now = utcnow()
    if key == "ready":
        return [Repair.status == "Готово к выдаче"]
    if key == "waiting-parts":
        return [Repair.status == "Ожидание запчастей"]
    if key == "today":
        return [Repair.accepted_at >= _today_start_utc()]
    if key == "in-repair":
        return [Repair.status.in_(IN_PROCESS_STATUSES)]
    if key == "not-picked-up":
        three = now - timedelta(days=3)
        return [
            or_(
                Repair.status == "Не забрано",
                and_(
                    Repair.status == "Готово к выдаче",
                    Repair.issued_at.is_(None),
                    Repair.ready_at.isnot(None),
                    Repair.ready_at < three,
                    or_(Repair.storage_until.is_(None), Repair.storage_until >= now),
                ),
            )
        ]
    if key == "disposable":
        return [
            Repair.storage_until.isnot(None),
            Repair.storage_until < now,
            Repair.status.notin_(list(CLOSED_STATUSES)),
        ]
    if key == "warranty":
        return [
            Repair.status == "Выдано",
            Repair.warranty_text.isnot(None),
            Repair.warranty_text != "",
        ]
    return []


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
    now = utcnow()
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

    async def _metric(key: str) -> int:
        clauses = dashboard_filter_clauses(key)
        stmt = select(func.count(Repair.id))
        if clauses:
            stmt = stmt.where(*clauses)
        return int((await db.execute(stmt)).scalar_one() or 0)

    return {
        "total": total,
        "all_repairs": int(total or 0),
        "active": active,
        "ready": await _metric("ready"),
        "waiting_parts": await _metric("waiting-parts"),
        "accepted_today": await _metric("today"),
        "in_repair": await _metric("in-repair"),
        "not_picked_up": await _metric("not-picked-up"),
        "disposable": await _metric("disposable"),
        "warranty": await _metric("warranty"),
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


def _fmt_day(d: date) -> str:
    return f"{d.day} {_MONTHS_RU[d.month - 1]}"


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _period_window(
    period: str, date_from: str | None, date_to: str | None
) -> tuple[datetime, datetime, str, date, date]:
    now_local = datetime.now(ASHGABAT)
    today = now_local.date()
    grain = "day"
    start_d, end_d = today, today

    if period not in PERIOD_LABELS:
        period = "14d"

    if period == "today":
        start_d = end_d = today
        grain = "hour"
    elif period == "week":
        start_d = today - timedelta(days=6)
        grain = "day"
    elif period == "14d":
        start_d = today - timedelta(days=13)
        grain = "day"
    elif period == "month":
        start_d = today - timedelta(days=29)
        grain = "day"
    elif period == "3m":
        start_d = today - timedelta(days=89)
        grain = "week"
    elif period == "6m":
        start_d = today - timedelta(days=179)
        grain = "week"
    elif period == "year":
        start_d = date(today.year - 1, today.month, 1)
        grain = "month"
    elif period == "custom":
        try:
            start_d = date.fromisoformat(date_from or "")
            end_d = date.fromisoformat(date_to or "")
        except ValueError:
            start_d = today - timedelta(days=13)
            end_d = today
        if end_d < start_d:
            start_d, end_d = end_d, start_d
        span = (end_d - start_d).days + 1
        if span <= 2:
            grain = "hour"
        elif span <= 62:
            grain = "day"
        elif span <= 370:
            grain = "week"
        else:
            grain = "month"
    elif period == "all":
        start_d = today - timedelta(days=365)
        grain = "month"

    start_local = datetime.combine(start_d, datetime.min.time(), tzinfo=ASHGABAT)
    if period == "today":
        end_local = now_local
    else:
        end_local = datetime.combine(end_d, datetime.max.time(), tzinfo=ASHGABAT)
        if end_local > now_local and period != "custom":
            end_local = now_local
    return _naive_utc(start_local), _naive_utc(end_local), grain, start_d, end_d


def _bucket_key(local_dt: datetime, grain: str):
    if grain == "hour":
        return local_dt.replace(tzinfo=None, minute=0, second=0, microsecond=0)
    if grain == "day":
        return local_dt.date()
    if grain == "week":
        return _monday(local_dt.date())
    return date(local_dt.year, local_dt.month, 1)


def _iter_buckets(start_d: date, end_d: date, grain: str) -> list:
    out = []
    if grain == "hour":
        cur = datetime.combine(start_d, datetime.min.time())
        last = datetime.combine(end_d, datetime.max.time()).replace(
            minute=0, second=0, microsecond=0
        )
        while cur <= last:
            out.append(cur)
            cur += timedelta(hours=1)
        return out
    if grain == "day":
        cur = start_d
        while cur <= end_d:
            out.append(cur)
            cur += timedelta(days=1)
        return out
    if grain == "week":
        cur = _monday(start_d)
        last = _monday(end_d)
        while cur <= last:
            out.append(cur)
            cur += timedelta(days=7)
        return out
    cur = date(start_d.year, start_d.month, 1)
    last = date(end_d.year, end_d.month, 1)
    while cur <= last:
        out.append(cur)
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return out


def _label_for(bucket, grain: str) -> str:
    if grain == "hour":
        return bucket.strftime("%H:%M")
    if grain == "month":
        return f"{_MONTHS_RU[bucket.month - 1]} {bucket.year}"
    return _fmt_day(bucket)


def _tooltip_for(bucket, grain: str) -> str:
    if grain == "hour":
        return f"{_fmt_day(bucket.date())} {bucket.strftime('%H:%M')}"
    if grain == "week":
        end = bucket + timedelta(days=6)
        return f"{_fmt_day(bucket)} — {_fmt_day(end)}"
    if grain == "month":
        return f"{_MONTHS_RU[bucket.month - 1]} {bucket.year}"
    return _fmt_day(bucket)


async def finance_chart(
    db: AsyncSession,
    period: str = "14d",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Ряды оборот / прибыль / расходы для графика панели."""
    from app.services.settings import get_currency

    period = (period or "14d").strip() or "14d"
    if period not in PERIOD_LABELS:
        period = "14d"

    start_utc, end_utc, grain, start_d, end_d = _period_window(period, date_from, date_to)

    if period == "all":
        pay_min = (await db.execute(select(func.min(Payment.paid_at)))).scalar()
        cost_min = (
            await db.execute(
                select(func.min(func.coalesce(Repair.issued_at, Repair.ready_at, Repair.accepted_at)))
            )
        ).scalar()
        candidates = [d for d in (pay_min, cost_min) if d]
        if candidates:
            first_local = _to_local(min(candidates))
            if first_local is not None:
                start_d = first_local.date()
                start_local = datetime.combine(start_d, datetime.min.time(), tzinfo=ASHGABAT)
                start_utc = _naive_utc(start_local)
            span = (end_d - start_d).days
            if span > 370:
                grain = "month"
            elif span > 62:
                grain = "week"
            else:
                grain = "day"

    buckets = _iter_buckets(start_d, end_d, grain) or [start_d]
    turnover_map: dict = defaultdict(float)
    expense_map: dict = defaultdict(float)

    pay_rows = (
        await db.execute(
            select(Payment.paid_at, Payment.amount).where(
                Payment.paid_at >= start_utc,
                Payment.paid_at <= end_utc,
            )
        )
    ).all()
    for paid_at, amount in pay_rows:
        local = _to_local(paid_at)
        if local is None:
            continue
        turnover_map[_bucket_key(local, grain)] += float(amount or 0)

    repair_rows = (
        await db.execute(
            select(
                Repair.issued_at,
                Repair.ready_at,
                Repair.accepted_at,
                Repair.cost_amount,
                Repair.master_payout,
            ).where(
                or_(
                    and_(Repair.issued_at.isnot(None), Repair.issued_at >= start_utc, Repair.issued_at <= end_utc),
                    and_(
                        Repair.issued_at.is_(None),
                        Repair.ready_at.isnot(None),
                        Repair.ready_at >= start_utc,
                        Repair.ready_at <= end_utc,
                    ),
                    and_(
                        Repair.issued_at.is_(None),
                        Repair.ready_at.is_(None),
                        Repair.accepted_at >= start_utc,
                        Repair.accepted_at <= end_utc,
                    ),
                )
            )
        )
    ).all()
    for issued_at, ready_at, accepted_at, cost_amount, master_payout in repair_rows:
        when = issued_at or ready_at or accepted_at
        local = _to_local(when)
        if local is None:
            continue
        expense_map[_bucket_key(local, grain)] += float(cost_amount or 0) + float(master_payout or 0)

    labels = [_label_for(b, grain) for b in buckets]
    tooltip_labels = [_tooltip_for(b, grain) for b in buckets]
    turnover = [round(turnover_map[b], 2) for b in buckets]
    expenses = [round(expense_map[b], 2) for b in buckets]
    profit = [round(t - e, 2) for t, e in zip(turnover, expenses)]

    cur = await get_currency(db)
    currency = (cur or {}).get("code") or "TMT"
    period_label = PERIOD_LABELS.get(period, "Период")
    caption = f"{period_label} · {_fmt_day(start_d)} — {_fmt_day(end_d)}"

    return {
        "ok": True,
        "period": period,
        "period_label": period_label,
        "caption": caption,
        "date_from": start_d.isoformat(),
        "date_to": end_d.isoformat(),
        "currency": currency,
        "labels": labels,
        "tooltip_labels": tooltip_labels,
        "turnover": turnover,
        "profit": profit,
        "expenses": expenses,
    }
