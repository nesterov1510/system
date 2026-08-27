"""Склад запчастей: каталог + привязка запчастей к ремонту.

Adding a part to a repair also debits stock and writes a repair event, so the
repair card and stats see the parts cost.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require_roles
from app.db.models import Part, Repair, RepairEvent, RepairPart, UserRole
from app.schemas.parts import (
    PartCreate,
    PartOut,
    PartUpdate,
    RepairPartAdd,
    RepairPartOut,
)

router = APIRouter(tags=["parts"])

CanEditParts = require_roles(UserRole.ADMIN.value, UserRole.MANAGER.value)


def _to_part_out(p: Part) -> PartOut:
    return PartOut(
        id=p.id,
        name=p.name,
        sku=p.sku,
        category=p.category,
        stock_qty=p.stock_qty,
        min_stock=p.min_stock,
        cost_price=p.cost_price,
        sell_price=p.sell_price,
        supplier=p.supplier,
        active=p.active,
        created_at=p.created_at,
    )


# --- Catalog ---
@router.get("/parts", response_model=list[PartOut])
async def list_parts(
    db: DbSession,
    user: CurrentUser,
    q: str | None = None,
    category: str | None = None,
    low_stock: bool = False,
):
    stmt = select(Part).order_by(Part.name)
    if q:
        stmt = stmt.where(Part.name.ilike(f"%{q}%"))
    if category:
        stmt = stmt.where(Part.category == category)
    if low_stock:
        stmt = stmt.where(Part.stock_qty <= Part.min_stock)
    row = await db.execute(stmt.limit(200))
    return [_to_part_out(p) for p in row.scalars().all()]


@router.get("/parts/categories")
async def list_categories(db: DbSession, user: CurrentUser):
    row = await db.execute(
        select(Part.category).where(Part.category.isnot(None)).distinct()
    )
    return [c for (c,) in row.all() if c]


@router.post("/parts", response_model=PartOut, status_code=201)
async def create_part(
    payload: PartCreate, db: DbSession, user: CurrentUser, _: bool = Depends(CanEditParts)
):
    p = Part(**payload.model_dump())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _to_part_out(p)


@router.patch("/parts/{part_id}", response_model=PartOut)
async def update_part(
    part_id: uuid.UUID,
    payload: PartUpdate,
    db: DbSession,
    user: CurrentUser,
    _: bool = Depends(CanEditParts),
):
    p = await db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "Запчасть не найдена")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(p, field, value)
    await db.commit()
    return _to_part_out(p)


@router.delete("/parts/{part_id}")
async def delete_part(
    part_id: uuid.UUID, db: DbSession, user: CurrentUser, _: bool = Depends(CanEditParts)
):
    p = await db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "Запчасть не найдена")
    p.active = False
    await db.commit()
    return {"ok": True}


# --- Repair parts ---
def _to_rp_out(rp: RepairPart) -> RepairPartOut:
    return RepairPartOut(
        id=rp.id,
        part_id=rp.part_id,
        part_name=rp.part.name,
        sku=rp.part.sku,
        qty=rp.qty,
        price=rp.price,
    )


@router.get("/repairs/{repair_id}/parts", response_model=list[RepairPartOut])
async def list_repair_parts(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    repair = await db.get(Repair, repair_id)
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    row = await db.execute(
        select(RepairPart)
        .options(selectinload(RepairPart.part))
        .where(RepairPart.repair_id == repair_id)
    )
    return [_to_rp_out(rp) for rp in row.scalars().all()]


@router.post("/repairs/{repair_id}/parts", response_model=RepairPartOut, status_code=201)
async def add_repair_part(
    repair_id: uuid.UUID,
    payload: RepairPartAdd,
    db: DbSession,
    user: CurrentUser,
):
    repair = await db.get(Repair, repair_id)
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    part = await db.get(Part, payload.part_id)
    if part is None:
        raise HTTPException(404, "Запчасть не найдена")

    # Upsert: if already attached, bump qty.
    row = await db.execute(
        select(RepairPart).where(
            RepairPart.repair_id == repair_id, RepairPart.part_id == part.id
        )
    )
    rp = row.scalar_one_or_none()
    if rp is not None:
        rp.qty += payload.qty
        if payload.price is not None:
            rp.price = payload.price
    else:
        rp = RepairPart(
            repair_id=repair_id,
            part_id=part.id,
            qty=payload.qty,
            price=payload.price if payload.price is not None else part.sell_price,
        )
        db.add(rp)

    # Debit stock.
    if part.stock_qty >= payload.qty:
        part.stock_qty -= payload.qty
    else:
        part.stock_qty = 0

    db.add(
        RepairEvent(
            repair_id=repair_id,
            type="comment",
            actor_id=user.id,
            data={"message": f"Добавлена запчасть: {part.name} ×{payload.qty}"},
        )
    )
    await db.commit()
    await db.refresh(rp)
    rp.part = part  # part is already loaded in this session
    return _to_rp_out(rp)


@router.delete("/repairs/{repair_id}/parts/{rp_id}")
async def remove_repair_part(
    repair_id: uuid.UUID, rp_id: uuid.UUID, db: DbSession, user: CurrentUser
):
    rp = await db.get(RepairPart, rp_id)
    if rp is None or rp.repair_id != repair_id:
        raise HTTPException(404, "Запчасть не найдена")
    # Return stock.
    part = await db.get(Part, rp.part_id)
    if part:
        part.stock_qty += rp.qty
    db.add(
        RepairEvent(
            repair_id=repair_id,
            type="comment",
            actor_id=user.id,
            data={"message": f"Убрана запчасть: {part.name if part else '—'} ×{rp.qty}"},
        )
    )
    await db.delete(rp)
    await db.commit()
    return {"ok": True}
