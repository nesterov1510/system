import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import AdminUser, DbSession
from app.services import stats as stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview")
async def overview(db: DbSession, user: AdminUser):
    return await stats_service.overview(db)


@router.get("/tiles")
async def tiles(
    db: DbSession,
    user: AdminUser,
    type: str | None = None,
    brand: str | None = None,
    model: str | None = None,
    city: uuid.UUID | None = None,
):
    return await stats_service.tiles(db, type_=type, brand=brand, model=model, city_id=city)
