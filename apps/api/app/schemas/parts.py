import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PartCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sku: str | None = None
    category: str | None = None
    stock_qty: int = 0
    min_stock: int = 0
    cost_price: float | None = None
    sell_price: float | None = None
    supplier: str | None = None
    active: bool = True


class PartUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    category: str | None = None
    stock_qty: int | None = None
    min_stock: int | None = None
    cost_price: float | None = None
    sell_price: float | None = None
    supplier: str | None = None
    active: bool | None = None


class PartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    sku: str | None = None
    category: str | None = None
    stock_qty: int
    min_stock: int
    cost_price: float | None = None
    sell_price: float | None = None
    supplier: str | None = None
    active: bool
    created_at: datetime


class RepairPartAdd(BaseModel):
    part_id: uuid.UUID
    qty: int = Field(default=1, ge=1)
    price: float | None = None


class RepairPartOut(BaseModel):
    id: uuid.UUID
    part_id: uuid.UUID
    part_name: str
    sku: str | None = None
    qty: int
    price: float | None = None
