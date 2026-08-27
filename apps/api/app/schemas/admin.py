import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CityCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=255)
    timezone: str = "Europe/Moscow"


class CityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    timezone: str
    created_at: datetime


class BranchCreate(BaseModel):
    city_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    address: str | None = None
    phone: str | None = None
    print_config: dict | None = None
    active: bool = True


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    city_id: uuid.UUID
    name: str
    address: str | None = None
    phone: str | None = None
    print_config: dict | None = None
    active: bool = True


class SettingIn(BaseModel):
    value: dict
    description: str | None = None


class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: dict | None = None
    description: str | None = None
