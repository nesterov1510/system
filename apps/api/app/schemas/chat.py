import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatUser(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    kind: str = "public"
    # Для личного (direct) канала — собеседник текущего пользователя.
    peer: ChatUser | None = None


class MessageAuthor(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID
    text: str
    repair_ref: str | None = None
    created_at: datetime
    author: MessageAuthor | None = None

    # preview fields (filled by router when repair_ref resolves)
    repair_preview: dict | None = None


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    repair_ref: str | None = None
