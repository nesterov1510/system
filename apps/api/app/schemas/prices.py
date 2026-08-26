import uuid

from pydantic import BaseModel, ConfigDict


class PriceItemCreate(BaseModel):
    device_type: str | None = None
    brand: str | None = None
    model_or_line: str | None = None
    fault: str | None = None
    city_id: uuid.UUID | None = None
    price_min: float | None = None
    price_max: float | None = None
    price_avg: float | None = None
    typical_days: int | None = None
    source: str | None = None
    active: bool = True


class PriceItemOut(PriceItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
