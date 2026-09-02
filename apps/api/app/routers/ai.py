from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import DbSession, require_roles
from app.db.models import UserRole
from app.services import ai as ai_service

router = APIRouter(prefix="/ai", tags=["ai"])

# AI-прогнозы и сводки относятся к аналитике — только админ/менеджер.
CanViewAnalytics = Depends(require_roles(UserRole.ADMIN.value, UserRole.MANAGER.value))


class PredictETABody(BaseModel):
    device_type: str
    brand: str | None = None
    fault: str | None = None
    city_id: str | None = None


@router.post("/predict-eta", dependencies=[CanViewAnalytics])
async def predict_eta(payload: PredictETABody, db: DbSession):
    return await ai_service.predict_eta(
        db,
        device_type=payload.device_type,
        brand=payload.brand,
        fault=payload.fault,
        city_id=payload.city_id,
    )


@router.post("/weekly-summary", dependencies=[CanViewAnalytics])
async def weekly_summary(db: DbSession):
    return await ai_service.weekly_summary(db)
