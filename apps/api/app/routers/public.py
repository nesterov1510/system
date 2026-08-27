from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession
from app.db.models import Branch, Repair
from app.schemas.repair import PublicRepairOut
from app.services.ratelimit import public_limiter
from app.services.settings import get_legal_text
from app.services.stats import city_stats

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/r/{token}", response_model=PublicRepairOut)
async def public_repair(token: str, db: DbSession, request: Request):
    # Rate-limit anonymous QR page.
    client_key = request.client.host if request.client else "unknown"
    if not public_limiter.allow(f"r:{client_key}"):
        raise HTTPException(429, "Слишком много запросов")

    row = await db.execute(
        select(Repair)
        .where(Repair.public_token == token)
        .options(selectinload(Repair.client))
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")

    branch_name = None
    branch_phone = None
    if repair.branch_id:
        branch = await db.get(Branch, repair.branch_id)
        if branch:
            branch_name = branch.name
            branch_phone = branch.phone

    legal_text = await get_legal_text(db)
    stats = await city_stats(db, repair.city_id, repair.device_type)

    return PublicRepairOut(
        number=repair.number,
        status=repair.status,
        device_type=repair.device_type,
        brand=repair.brand,
        model=repair.model,
        complectation=repair.complectation,
        accepted_at=repair.accepted_at,
        eta_days=repair.eta_days,
        ready_at=repair.ready_at,
        issued_at=repair.issued_at,
        storage_until=repair.storage_until,
        storage_text=legal_text,
        branch_name=branch_name,
        branch_phone=branch_phone,
        city_stats=stats,
    )
