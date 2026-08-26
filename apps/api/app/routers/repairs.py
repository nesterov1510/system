import uuid
from datetime import timedelta

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.db.models import Client, City, Repair, RepairEvent
from app.schemas.repair import (
    RepairCreate,
    RepairEventOut,
    RepairOut,
    RepairUpdate,
)
from app.services.numbering import next_repair_number, new_public_token, normalize_phone
from app.services.settings import get_storage_months
from app.ws.manager import manager

router = APIRouter(prefix="/repairs", tags=["repairs"])


def _serialize(repair: Repair) -> RepairOut:
    events = [
        RepairEventOut(
            id=e.id, type=e.type, actor_id=e.actor_id, data=e.data, created_at=e.created_at
        )
        for e in repair.events
    ]
    return RepairOut(
        id=repair.id,
        number=repair.number,
        public_token=repair.public_token,
        city_id=repair.city_id,
        branch_id=repair.branch_id,
        client_id=repair.client_id,
        device_type=repair.device_type,
        brand=repair.brand,
        model=repair.model,
        serial=repair.serial,
        complectation=repair.complectation,
        fault_client=repair.fault_client,
        fault_master=repair.fault_master,
        condition_notes=repair.condition_notes,
        accepted_by=repair.accepted_by,
        master_id=repair.master_id,
        status=repair.status,
        eta_days=repair.eta_days,
        eta_source=repair.eta_source,
        price_min=repair.price_min,
        price_max=repair.price_max,
        price_final=repair.price_final,
        accepted_at=repair.accepted_at,
        ready_at=repair.ready_at,
        issued_at=repair.issued_at,
        storage_until=repair.storage_until,
        print_count=repair.print_count,
        source=repair.source,
        events=events,
        client_name=repair.client.full_name,
        client_phone=repair.client.phone,
    )


async def _get_repair_or_404(db, repair_id: uuid.UUID) -> Repair:
    row = await db.execute(
        select(Repair)
        .where(Repair.id == repair_id)
        .options(
            selectinload(Repair.client),
            selectinload(Repair.events),
        )
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    return repair


@router.post("", response_model=RepairOut, status_code=201)
async def create_repair(
    payload: RepairCreate,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    # Idempotency: repeated submit with same key returns the existing repair.
    if idempotency_key:
        row = await db.execute(
            select(Repair).where(Repair.idempotency_key == idempotency_key)
        )
        existing = row.scalar_one_or_none()
        if existing is not None:
            existing = await _get_repair_or_404(db, existing.id)
            return _serialize(existing)

    city = await db.get(City, payload.city_id)
    if city is None:
        raise HTTPException(400, "Город не найден")

    # Upsert client by normalized phone.
    phone_norm = normalize_phone(payload.client.phone)
    row = await db.execute(select(Client).where(Client.phone_norm == phone_norm))
    client = row.scalar_one_or_none()
    if client is None:
        client = Client(
            full_name=payload.client.full_name,
            phone=payload.client.phone,
            phone_norm=phone_norm,
        )
        db.add(client)
        await db.flush()
    else:
        client.full_name = payload.client.full_name

    from app.db.base import utcnow

    number = await next_repair_number(db, city, payload.device_type)
    storage_months = await get_storage_months(db)
    now = utcnow()

    repair = Repair(
        number=number,
        public_token=new_public_token(),
        city_id=payload.city_id,
        branch_id=payload.branch_id,
        client_id=client.id,
        device_type=payload.device_type,
        brand=payload.brand,
        model=payload.model,
        serial=payload.serial,
        complectation=payload.complectation,
        fault_client=payload.fault_client,
        condition_notes=payload.condition_notes,
        accepted_by=user.id,
        master_id=payload.master_id,
        status="Принято",
        eta_days=payload.eta_days,
        eta_source=payload.eta_source,
        accepted_at=now,
        storage_until=now + timedelta(days=storage_months * 30),
        source=payload.source,
        idempotency_key=idempotency_key,
    )
    db.add(repair)
    await db.flush()

    db.add(
        RepairEvent(
            repair_id=repair.id,
            type="status_change",
            actor_id=user.id,
            data={"to": "Принято", "from": None},
        )
    )
    await db.commit()

    repair = await _get_repair_or_404(db, repair.id)

    # Notify the chat: new acceptance.
    await manager.broadcast(
        {
            "type": "repair.created",
            "repair": {"number": repair.number, "status": repair.status},
        }
    )
    return _serialize(repair)


@router.get("", response_model=list[RepairOut])
async def list_repairs(
    db: DbSession,
    user: CurrentUser,
    status: str | None = None,
    master_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    q_stmt = (
        select(Repair)
        .options(selectinload(Repair.client), selectinload(Repair.events))
        .order_by(Repair.accepted_at.desc())
    )
    if status:
        q_stmt = q_stmt.where(Repair.status == status)
    if master_id:
        q_stmt = q_stmt.where(Repair.master_id == master_id)
    if q:
        like = f"%{q}%"
        q_stmt = q_stmt.where(
            (Repair.number.ilike(like)) | (Repair.client.has(Client.phone.ilike(like)))
        )
    q_stmt = q_stmt.limit(limit).offset(offset)
    row = await db.execute(q_stmt)
    return [_serialize(r) for r in row.scalars().all()]


@router.get("/by-number/{number}", response_model=RepairOut)
async def get_by_number(number: str, db: DbSession, user: CurrentUser):
    row = await db.execute(
        select(Repair)
        .where(Repair.number == number)
        .options(selectinload(Repair.client), selectinload(Repair.events))
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    return _serialize(repair)


@router.get("/{repair_id}", response_model=RepairOut)
async def get_repair(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    return _serialize(await _get_repair_or_404(db, repair_id))


@router.patch("/{repair_id}", response_model=RepairOut)
async def update_repair(
    repair_id: uuid.UUID, payload: RepairUpdate, db: DbSession, user: CurrentUser
):
    repair = await _get_repair_or_404(db, repair_id)

    from app.db.base import utcnow

    old_status = repair.status
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(repair, field, value)

    if payload.status and payload.status != old_status:
        repair.events.append(
            RepairEvent(
                repair_id=repair.id,
                type="status_change",
                actor_id=user.id,
                data={"from": old_status, "to": payload.status},
            )
        )
        if payload.status == "Готово к выдаче":
            repair.ready_at = utcnow()
        if payload.status == "Выдано":
            repair.issued_at = utcnow()

    await db.commit()
    repair = await _get_repair_or_404(db, repair.id)

    if payload.status and payload.status != old_status:
        await manager.broadcast(
            {
                "type": "repair.status_changed",
                "repair": {"number": repair.number, "status": payload.status},
            }
        )
    return _serialize(repair)


@router.post("/{repair_id}/events", response_model=RepairOut)
async def add_event(
    repair_id: uuid.UUID, db: DbSession, user: CurrentUser, comment: dict
):
    repair = await _get_repair_or_404(db, repair_id)
    repair.events.append(
        RepairEvent(
            repair_id=repair.id,
            type="comment",
            actor_id=user.id,
            data={"message": comment.get("message", "")},
        )
    )
    await db.commit()
    return _serialize(await _get_repair_or_404(db, repair_id))
