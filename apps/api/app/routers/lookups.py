"""Lookup endpoints for authenticated staff (operators/masters/etc).

Cities/branches/masters/complectation are needed by the acceptance form, which
non-admin roles use too — so these live here (not behind admin-only).
"""
from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.db.models import Branch, City, ComplectationItem, User, UserRole

router = APIRouter(prefix="/lookups", tags=["lookups"])


@router.get("/cities")
async def list_cities(db: DbSession, user: CurrentUser):
    row = await db.execute(select(City).order_by(City.name))
    return [
        {"id": c.id, "slug": c.slug, "name": c.name, "timezone": c.timezone}
        for c in row.scalars().all()
    ]


@router.get("/branches")
async def list_branches(db: DbSession, user: CurrentUser):
    row = await db.execute(
        select(Branch).where(Branch.active.is_(True)).order_by(Branch.name)
    )
    return [
        {"id": b.id, "city_id": b.city_id, "name": b.name, "address": b.address}
        for b in row.scalars().all()
    ]


@router.get("/masters")
async def list_masters(db: DbSession, user: CurrentUser):
    """Все активные пользователи, у которых есть роль «мастер» —

    основная или дополнительная (пользователю можно назначить несколько
    ролей, напр. admin ещё и master).
    """
    row = await db.execute(
        select(User).where(User.active.is_(True)).order_by(User.name)
    )
    return [
        {"id": u.id, "name": u.name}
        for u in row.scalars().all()
        if u.has_role(UserRole.MASTER.value)
    ]


@router.get("/complectation-items")
async def list_complectation(db: DbSession, user: CurrentUser):
    row = await db.execute(
        select(ComplectationItem).order_by(ComplectationItem.sort)
    )
    return [{"id": c.id, "name": c.name} for c in row.scalars().all()]
