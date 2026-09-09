"""Запросы данных для серверных страниц.

Чтения — прямыми SQLAlchemy-запросами (с теми же ограничениями прав мастера,
что и JSON-API: `_master_scope`). Мутации выполняют функции API-роутеров,
поэтому бизнес-логика (нумерация, аудит, SMS, события) не дублируется.
"""
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.db.models import (
    Client,
    Payment,
    Repair,
    RepairMaster,
    RepairPart,
)
from app.webui.catalog import STAGES

STAGE_STATUSES = {key: statuses for key, _label, statuses in STAGES}


def master_scope(user_id: uuid.UUID):
    subq = select(RepairMaster.repair_id).where(RepairMaster.user_id == user_id)
    return or_(Repair.master_id == user_id, Repair.id.in_(subq))


def is_master_only(user) -> bool:
    from app.core.permissions import is_master_only as _imo
    return _imo(user)


async def fetch_repairs(
    db,
    user,
    *,
    stage: str | None = None,
    status: str | None = None,
    q: str | None = None,
    master_id: uuid.UUID | None = None,
    unassigned: bool = False,
    page: int = 1,
    page_size: int = 50,
):
    filters = []
    if stage and stage != "all" and stage in STAGE_STATUSES:
        filters.append(Repair.status.in_(STAGE_STATUSES[stage]))
    if status:
        filters.append(Repair.status == status)
    if master_id:
        filters.append(Repair.master_id == master_id)
    if unassigned:
        filters.append(Repair.master_id.is_(None))
        filters.append(Repair.id.not_in(select(RepairMaster.repair_id)))
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Repair.number.ilike(like),
                Repair.serial.ilike(like),
                Repair.client.has(Client.phone.ilike(like)),
                Repair.client.has(Client.full_name.ilike(like)),
                Repair.brand.ilike(like),
                Repair.model.ilike(like),
            )
        )
    if is_master_only(user):
        filters.append(master_scope(user.id))

    base = select(Repair).where(*filters)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    rows = (
        await db.execute(
            base.options(
                selectinload(Repair.client),
                selectinload(Repair.master),
                selectinload(Repair.accepted_by_user),
                selectinload(Repair.masters).selectinload(RepairMaster.user),
            )
            .order_by(Repair.accepted_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    # Сводка по запчастям и платежам для таблицы.
    result = []
    for r in rows:
        result.append(r)
    return result, total


async def repair_parts_cost(db, repair_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    if not repair_ids:
        return {}
    rows = (
        await db.execute(
            select(RepairPart.repair_id, func.coalesce(func.sum(RepairPart.price * RepairPart.qty), 0))
            .where(RepairPart.repair_id.in_(repair_ids))
            .group_by(RepairPart.repair_id)
        )
    ).all()
    return {rid: float(cost) for rid, cost in rows}


async def repair_parts_names(db, repair_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Названия запчастей по ремонтам (для колонки «Запчасти» таблицы)."""
    if not repair_ids:
        return {}
    rows = (
        await db.execute(
            select(RepairPart)
            .options(selectinload(RepairPart.part))
            .where(RepairPart.repair_id.in_(repair_ids))
            .order_by(RepairPart.created_at)
        )
    ).scalars().all()
    out: dict[uuid.UUID, list[str]] = {}
    for rp in rows:
        if not rp.part:
            continue
        name = f"{rp.part.name} ×{rp.qty}" if rp.qty and rp.qty > 1 else rp.part.name
        out.setdefault(rp.repair_id, []).append(name)
    return out


async def repair_payments_total(db, repair_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    if not repair_ids:
        return {}
    rows = (
        await db.execute(
            select(Payment.repair_id, func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.repair_id.in_(repair_ids))
            .group_by(Payment.repair_id)
        )
    ).all()
    return {rid: float(total) for rid, total in rows}


def stage_of(status: str) -> str:
    for key, _label, statuses in STAGES:
        if status in statuses:
            return key
    return "work"


def repair_profit(repair) -> float:
    """Остаток после расходов: сумма − запчасти − выплата мастерам."""
    gross = repair.price_final if repair.price_final is not None else (repair.price_max or 0)
    return float(gross or 0) - float(getattr(repair, "_parts_cost", 0) or 0) - float(repair.master_payout or 0)
