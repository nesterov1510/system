import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import EquipmentStatus

VALID_STATUSES = {s.value for s in EquipmentStatus}


def to_naive_utc(v: datetime | None) -> datetime | None:
    """Вся БД хранит naive UTC (см. utcnow() в models). asyncpg падает с
    DataError, если в naive TIMESTAMP-колонку передать aware-datetime —
    поэтому входящие значения с таймзоной приводим к naive UTC."""
    if v is not None and v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


class EquipmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = None
    model: str | None = None
    # За сколько купили (ман.).
    purchase_price: float | None = None
    # Дата покупки (по умолчанию — сегодня).
    purchased_at: datetime | None = None
    status: str = EquipmentStatus.IN_STOCK.value
    # Какие комплектующие внутри (опционально).
    components: list[str] | None = None
    # Где лежит (напр. «Склад, полка 3»).
    storage_place: str | None = None
    notes: str | None = None

    @field_validator("purchased_at", mode="after")
    @classmethod
    def _naive_utc(cls, v):
        return to_naive_utc(v)

    @model_validator(mode="after")
    def _check_status(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Недопустимый статус: {self.status}")
        return self


class EquipmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    brand: str | None = None
    model: str | None = None
    purchase_price: float | None = None
    purchased_at: datetime | None = None
    status: str | None = None
    components: list[str] | None = None
    storage_place: str | None = None
    notes: str | None = None
    active: bool | None = None

    @field_validator("purchased_at", mode="after")
    @classmethod
    def _naive_utc(cls, v):
        return to_naive_utc(v)

    @model_validator(mode="after")
    def _check_status(self):
        if self.status is not None and self.status not in VALID_STATUSES:
            raise ValueError(f"Недопустимый статус: {self.status}")
        return self


class EquipmentStatusSet(BaseModel):
    """Быстрые действия из списка: «разобран» / «частично разобран»."""

    status: str

    @model_validator(mode="after")
    def _check_status(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Недопустимый статус: {self.status}")
        return self


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    brand: str | None = None
    model: str | None = None
    purchase_price: float | None = None
    purchased_at: datetime
    status: str
    components: list[str] | None = None
    storage_place: str | None = None
    notes: str | None = None
    active: bool
    created_at: datetime
