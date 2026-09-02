import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    phone: str | None = None
    telegram: str | None = None
    role: str
    city_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    active: bool = True
    created_at: datetime


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str
    phone: str | None = None
    telegram: str | None = None
    password: str = Field(min_length=6)
    role: str = "operator"
    city_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    active: bool = True


class UserUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    telegram: str | None = None
    role: str | None = None
    city_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=6)
