import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClientCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=5, max_length=32)
    consent_pdn: bool = False
    consent_storage: bool = False


class RepairCreate(BaseModel):
    """Minimal acceptance payload (Iteration 2 extends this with photos)."""

    city_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    client: ClientCreate
    device_type: str = Field(min_length=1, max_length=32)
    brand: str | None = None
    model: str | None = None
    serial: str | None = None
    complectation: dict | None = None
    fault_client: str | None = None
    condition_notes: str | None = None
    master_id: uuid.UUID | None = None
    eta_days: int | None = None
    eta_source: str | None = None
    source: str = "walkin"


class RepairUpdate(BaseModel):
    status: str | None = None
    master_id: uuid.UUID | None = None
    fault_master: str | None = None
    eta_days: int | None = None
    eta_source: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    price_final: float | None = None


class RepairEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    actor_id: uuid.UUID | None = None
    data: dict | None = None
    created_at: datetime


class RepairOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    public_token: str
    city_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    client_id: uuid.UUID
    device_type: str
    brand: str | None = None
    model: str | None = None
    serial: str | None = None
    complectation: dict | None = None
    fault_client: str | None = None
    fault_master: str | None = None
    condition_notes: str | None = None
    accepted_by: uuid.UUID
    master_id: uuid.UUID | None = None
    status: str
    eta_days: int | None = None
    eta_source: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    price_final: float | None = None
    accepted_at: datetime
    ready_at: datetime | None = None
    issued_at: datetime | None = None
    storage_until: datetime | None = None
    print_count: int
    source: str
    events: list[RepairEventOut] = []

    # denormalized client info for list/card rendering
    client_name: str | None = None
    client_phone: str | None = None


class PublicRepairOut(BaseModel):
    """Limited DTO for the anonymous QR page — no internal data."""

    number: str
    status: str
    device_type: str
    brand: str | None = None
    model: str | None = None
    complectation: dict | None = None
    accepted_at: datetime
    eta_days: int | None = None
    ready_at: datetime | None = None
    issued_at: datetime | None = None
    storage_until: datetime | None = None
    storage_text: str | None = None
    branch_name: str | None = None
    branch_phone: str | None = None
