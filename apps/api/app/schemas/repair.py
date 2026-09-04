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
    # Второй контакт по этому ремонту (напр. владелец техники ≠ тот, кто
    # доставил её в сервис — разные люди, разные номера).
    contact2_name: str | None = None
    contact2_phone: str | None = None
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
    consent_repair: bool = False
    # Заказ доставлен курьером / забран с адреса клиента.
    is_delivery: bool = False


class RepairUpdate(BaseModel):
    status: str | None = None
    master_id: uuid.UUID | None = None
    # Несколько мастеров на ремонт (в бланке — строки «Inžiner»).
    # Первый в списке становится основным (master_id).
    master_ids: list[uuid.UUID] | None = None
    # Помощники мастера (в бланке — «Inžiner (kömekçi)»). Пользователю можно
    # назначить помощника независимо от списка основных мастеров.
    helper_ids: list[uuid.UUID] | None = None
    fault_master: str | None = None
    eta_days: int | None = None
    eta_source: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    price_final: float | None = None
    cost_amount: float | None = None
    # Сколько выплачено мастерам по этому ремонту (вручную).
    master_payout: float | None = None
    paid: bool | None = None
    # Что починили (для бланка) и гарантия на ремонт.
    work_done: str | None = None
    warranty_text: str | None = None
    contact2_name: str | None = None
    contact2_phone: str | None = None
    is_delivery: bool | None = None


class RepairEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    actor_id: uuid.UUID | None = None
    data: dict | None = None
    created_at: datetime


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repair_id: uuid.UUID
    caption: str | None = None
    created_at: datetime
    url: str = ""


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
    consent_repair_at: datetime | None = None
    accepted_by: uuid.UUID
    master_id: uuid.UUID | None = None
    status: str
    eta_days: int | None = None
    eta_source: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    price_final: float | None = None
    cost_amount: float | None = None
    paid: bool = False
    work_done: str | None = None
    warranty_text: str | None = None
    accepted_at: datetime
    ready_at: datetime | None = None
    issued_at: datetime | None = None
    storage_until: datetime | None = None
    print_count: int
    source: str
    events: list[RepairEventOut] = []
    contact2_name: str | None = None
    contact2_phone: str | None = None
    is_delivery: bool = False

    # denormalized client info for list/card rendering
    client_name: str | None = None
    client_phone: str | None = None
    # Кто принял технику (имя сотрудника) — для колонки списка.
    accepted_by_name: str | None = None
    # Сколько выплачено мастерам по этому ремонту.
    master_payout: float | None = None
    # Сводка по запчастям ремонта: сумма и строки «название ×кол-во».
    parts_cost: float | None = None
    parts_names: list[str] = []
    # denormalized master info
    master_name: str | None = None
    # все мастера ремонта (по порядку; первый — основной)
    master_ids: list[uuid.UUID] = []
    master_names: list[str] = []
    # помощники мастера (в бланке — «Inžiner (kömekçi)»)
    helper_ids: list[uuid.UUID] = []
    helper_names: list[str] = []


class PartOrderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    qty: int = Field(default=1, ge=1)
    ordered_at: datetime | None = None
    price: float | None = None


class PartOrderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    qty: int | None = Field(default=None, ge=1)
    ordered_at: datetime | None = None
    received_at: datetime | None = None
    price: float | None = None


class PartOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repair_id: uuid.UUID
    name: str
    qty: int
    ordered_at: datetime | None = None
    received_at: datetime | None = None
    price: float | None = None
    created_at: datetime


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
    city_stats: dict | None = None


class RepairsPage(BaseModel):
    """Пейджированный список ремонтов для страницы «Все ремонты»."""

    items: list[RepairOut] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
