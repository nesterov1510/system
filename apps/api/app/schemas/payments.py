import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    amount: float = Field(gt=0)
    method: str = Field(default="cash", pattern="^(cash|card|transfer)$")


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repair_id: uuid.UUID
    amount: float
    method: str
    operator_id: uuid.UUID | None = None
    paid_at: datetime
