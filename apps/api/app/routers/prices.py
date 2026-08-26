"""Price catalog + hints for the acceptance form and diagnosis.

GET /prices?type=&brand=&model=&city=&fault= returns matching items (fuzzy:
exact type/brand, then looser). The acceptance form uses this to hint a
price range; diagnosis (master) uses it for agreement.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require_roles
from app.db.models import PriceItem, UserRole
from app.schemas.prices import PriceItemCreate, PriceItemOut

router = APIRouter(prefix="/prices", tags=["prices"])

# Admin/manager can mutate prices; everyone can read.
CanEditPrices = require_roles(UserRole.ADMIN.value, UserRole.MANAGER.value)


def _to_out(p: PriceItem) -> PriceItemOut:
    return PriceItemOut(
        id=p.id,
        device_type=p.device_type,
        brand=p.brand,
        model_or_line=p.model_or_line,
        fault=p.fault,
        city_id=p.city_id,
        price_min=p.price_min,
        price_max=p.price_max,
        price_avg=p.price_avg,
        typical_days=p.typical_days,
        source=p.source,
        active=p.active,
    )


@router.get("", response_model=list[PriceItemOut])
async def search_prices(
    db: DbSession,
    user: CurrentUser,
    type: str | None = None,
    brand: str | None = None,
    model: str | None = None,
    city: uuid.UUID | None = None,
    fault: str | None = None,
    limit: int = Query(20, le=100),
):
    q = select(PriceItem).where(PriceItem.active.is_(True))

    if type:
        q = q.where(PriceItem.device_type == type)
    if brand:
        q = q.where(PriceItem.brand == brand)
    if city:
        q = q.where(PriceItem.city_id == city)
    if fault:
        q = q.where(PriceItem.fault.ilike(f"%{fault}%"))
    if model:
        q = q.where(
            (PriceItem.model_or_line == model)
            | (PriceItem.model_or_line.is_(None))
        )

    row = await db.execute(q.order_by(PriceItem.price_avg).limit(limit))
    items = row.scalars().all()

    # Loosen: if nothing exact, drop brand/model/fault filters progressively.
    if not items:
        q = select(PriceItem).where(PriceItem.active.is_(True))
        if type:
            q = q.where(PriceItem.device_type == type)
        if city:
            q = q.where(PriceItem.city_id == city)
        row = await db.execute(q.order_by(PriceItem.price_avg).limit(limit))
        items = row.scalars().all()

    return [_to_out(p) for p in items]


async def _aggregate(db, type_, brand, city, fault) -> dict | None:
    """Aggregate matching prices into a range (min–max) + typical days."""
    items = await search_prices(
        db, None, type=type_, brand=brand, city=city, fault=fault, limit=100
    )
    if not items:
        return None
    mins = [p.price_min for p in items if p.price_min is not None]
    maxs = [p.price_max for p in items if p.price_max is not None]
    days = [p.typical_days for p in items if p.typical_days is not None]
    result = {}
    if mins:
        result["price_min"] = min(mins)
    if maxs:
        result["price_max"] = max(maxs)
    if days:
        result["typical_days_min"] = min(days)
        result["typical_days_max"] = max(days)
    result["n"] = len(items)
    return result


@router.get("/hint", response_model=dict)
async def price_hint(
    db: DbSession,
    user: CurrentUser,
    type: str | None = None,
    brand: str | None = None,
    city: uuid.UUID | None = None,
    fault: str | None = None,
):
    agg = await _aggregate(db, type, brand, city, fault)
    if agg is None:
        return {"hint": None, "message": "нет данных по прайсу"}
    return {"hint": agg}


@router.post("", response_model=PriceItemOut, status_code=201)
async def create_price(
    payload: PriceItemCreate,
    db: DbSession,
    user: CurrentUser,
    _: bool = Depends(CanEditPrices),
):
    p = PriceItem(**payload.model_dump())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _to_out(p)


@router.patch("/{price_id}", response_model=PriceItemOut)
async def update_price(
    price_id: uuid.UUID,
    payload: PriceItemCreate,
    db: DbSession,
    user: CurrentUser,
    _: bool = Depends(CanEditPrices),
):
    p = await db.get(PriceItem, price_id)
    if p is None:
        raise HTTPException(404, "Позиция прайса не найдена")
    for field, value in payload.model_dump().items():
        setattr(p, field, value)
    await db.commit()
    return _to_out(p)


@router.delete("/{price_id}")
async def delete_price(
    price_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    _: bool = Depends(require_roles(UserRole.ADMIN.value)),
):
    p = await db.get(PriceItem, price_id)
    if p is None:
        raise HTTPException(404, "Позиция прайса не найдена")
    p.active = False  # soft-delete keeps history
    await db.commit()
    return {"ok": True}
