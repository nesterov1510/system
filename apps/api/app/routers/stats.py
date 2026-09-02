import uuid

from fastapi import APIRouter
from sqlalchemy import select

import uuid

from fastapi import Depends

from app.core.deps import DbSession, require_roles
from app.db.models import UserRole
from app.services import stats as stats_service

router = APIRouter(prefix="/stats", tags=["stats"])

# Аналитика/отчёты доступны только админу и менеджеру
# (по ролям оператору и мастеру она недоступна).
CanViewAnalytics = Depends(require_roles(UserRole.ADMIN.value, UserRole.MANAGER.value))


@router.get("/overview", dependencies=[CanViewAnalytics])
async def overview(db: DbSession):
    return await stats_service.overview(db)


@router.get("/tiles", dependencies=[CanViewAnalytics])
async def tiles(
    db: DbSession,
    type: str | None = None,
    brand: str | None = None,
    model: str | None = None,
    city: uuid.UUID | None = None,
):
    return await stats_service.tiles(db, type_=type, brand=brand, model=model, city_id=city)
