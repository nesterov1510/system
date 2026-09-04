"""Склад: купленная техника.

Админ добавляет купленную технику, указывает за сколько купили и опционально
какие комплектующие внутри. Список: дата, название, марка/модель, цена покупки,
статус (в наличии / частично разобран / разобран).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select

from app.core.deps import CurrentUser, DbSession, require_roles
from app.db.models import Equipment, EquipmentStatus, UserRole
from app.schemas.equipment import (
    EquipmentCreate,
    EquipmentOut,
    EquipmentStatusSet,
    EquipmentUpdate,
)

router = APIRouter(tags=["equipment"])

CanEditEquipment = require_roles(UserRole.ADMIN.value, UserRole.MANAGER.value)

STATUS_LABELS = {
    EquipmentStatus.IN_STOCK.value: "В наличии",
    EquipmentStatus.PARTIAL.value: "Частично разобран",
    EquipmentStatus.DISMANTLED.value: "Разобран",
}


def _to_out(e: Equipment) -> EquipmentOut:
    return EquipmentOut.model_validate(e)


# --- List / read ---
@router.get("/equipment", response_model=list[EquipmentOut])
async def list_equipment(
    db: DbSession,
    user: CurrentUser,
    q: str | None = None,
    status: str | None = None,
):
    stmt = select(Equipment).where(Equipment.active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Equipment.name.ilike(like),
                Equipment.brand.ilike(like),
                Equipment.model.ilike(like),
                Equipment.storage_place.ilike(like),
            )
        )
    if status:
        stmt = stmt.where(Equipment.status == status)
    row = await db.execute(stmt.order_by(Equipment.purchased_at.desc(), Equipment.name))
    return [_to_out(e) for e in row.scalars().all()]


@router.get("/equipment/{equipment_id}", response_model=EquipmentOut)
async def get_equipment(equipment_id: uuid.UUID, db: DbSession, user: CurrentUser):
    e = await db.get(Equipment, equipment_id)
    if e is None or not e.active:
        raise HTTPException(404, "Техника не найдена")
    return _to_out(e)


# --- Create / update / delete (admin) ---
@router.post("/equipment", response_model=EquipmentOut, status_code=201)
async def create_equipment(
    payload: EquipmentCreate, db: DbSession, user: CurrentUser, _: bool = Depends(CanEditEquipment)
):
    e = Equipment(**payload.model_dump())
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return _to_out(e)


@router.patch("/equipment/{equipment_id}", response_model=EquipmentOut)
async def update_equipment(
    equipment_id: uuid.UUID,
    payload: EquipmentUpdate,
    db: DbSession,
    user: CurrentUser,
    _: bool = Depends(CanEditEquipment),
):
    e = await db.get(Equipment, equipment_id)
    if e is None or not e.active:
        raise HTTPException(404, "Техника не найдена")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(e, field, value)
    await db.commit()
    return _to_out(e)


@router.delete("/equipment/{equipment_id}")
async def delete_equipment(
    equipment_id: uuid.UUID, db: DbSession, user: CurrentUser, _: bool = Depends(CanEditEquipment)
):
    e = await db.get(Equipment, equipment_id)
    if e is None or not e.active:
        raise HTTPException(404, "Техника не найдена")
    # Мягкое удаление (как у запчастей) — история покупок сохраняется.
    e.active = False
    await db.commit()
    return {"ok": True}


# --- Быстрые действия: «разобран» / «частично разобран» ---
@router.post("/equipment/{equipment_id}/status", response_model=EquipmentOut)
async def set_equipment_status(
    equipment_id: uuid.UUID,
    payload: EquipmentStatusSet,
    db: DbSession,
    user: CurrentUser,
    _: bool = Depends(CanEditEquipment),
):
    e = await db.get(Equipment, equipment_id)
    if e is None or not e.active:
        raise HTTPException(404, "Техника не найдена")
    e.status = payload.status
    await db.commit()
    return _to_out(e)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)
