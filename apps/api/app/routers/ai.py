from fastapi import APIRouter
from pydantic import BaseModel

from app.core.deps import AdminUser, DbSession
from app.services import ai as ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


class PredictETABody(BaseModel):
    device_type: str
    brand: str | None = None
    fault: str | None = None
    city_id: str | None = None


@router.post("/predict-eta")
async def predict_eta(payload: PredictETABody, db: DbSession, user: AdminUser):
    return await ai_service.predict_eta(
        db,
        device_type=payload.device_type,
        brand=payload.brand,
        fault=payload.fault,
        city_id=payload.city_id,
    )


@router.post("/weekly-summary")
async def weekly_summary(db: DbSession, user: AdminUser):
    return await ai_service.weekly_summary(db)
