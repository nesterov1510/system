"""SQLAlchemy ORM models — the single source of truth for the data layer."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, utcnow


def gen_uuid() -> uuid.UUID:
    return uuid.uuid4()


# JSON type that degrades to plain JSON on SQLite and JSONB on Postgres.
JSONType = JSON().with_variant(JSONB(), "postgresql")


# --------------------------------------------------------------------------
# Enums (values are the source of truth for roles/statuses; string-based for
# portability between SQLite (dev) and Postgres (prod)).
# --------------------------------------------------------------------------
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"
    MASTER = "master"
    CALLCENTER = "callcenter"


class RepairSource(str, enum.Enum):
    WALKIN = "walkin"
    CALL = "call"
    SITE = "site"


class ETASource(str, enum.Enum):
    MANUAL = "manual"
    STATS = "stats"
    AI = "ai"


class EventType(str, enum.Enum):
    STATUS_CHANGE = "status_change"
    COMMENT = "comment"
    PRINT = "print"
    CALL = "call"
    PRICE = "price"
    PHOTO = "photo"
    ASSIGN = "assign"
    NOTIFY = "notify"


# Default, overridable list (stored in settings['repair_statuses'] on seed).
DEFAULT_REPAIR_STATUSES = [
    "Принято",
    "Диагностика",
    "Согласование",
    "Ожидание запчастей",
    "В ремонте",
    "Готово к выдаче",
    "Выдано",
    "Не забрано",
    "Архив",
    "Отказ",
]


# --------------------------------------------------------------------------
# Users / org structure
# --------------------------------------------------------------------------
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    telegram: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Основная (первая) роль — используется для бейджей и обратной совместимости.
    role: Mapped[str] = mapped_column(String(32), default=UserRole.OPERATOR.value)
    # Дополнительные роли пользователя (сверх основной `role`). Одному
    # сотруднику можно назначить несколько ролей: напр. admin ещё и master.
    # Полный список — см. свойство `roles` ниже.
    extra_roles: Mapped[list | None] = mapped_column(
        # Отдельный экземпляр JSON-типа: `Mutable.as_mutable()` регистрирует
        # слушателей на самом объекте типа, поэтому его нельзя переиспользовать
        # между колонкой-списком (roles) и колонками-словарями (see JSONType).
        "roles", MutableList.as_mutable(JSON().with_variant(JSONB(), "postgresql")), nullable=True
    )
    city_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("cities.id"), nullable=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("branches.id"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def roles(self) -> list[str]:
        """Все роли пользователя (основная + дополнительные), без дублей."""
        extra = self.extra_roles if isinstance(self.extra_roles, list) else []
        result: list[str] = []
        for r in [self.role, *extra]:
            if r and r not in result:
                result.append(r)
        return result

    def has_role(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles)


class City(Base, TimestampMixin):
    __tablename__ = "cities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    slug: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ashgabat")

    branches: Mapped[list["Branch"]] = relationship(
        back_populates="city", cascade="all, delete-orphan"
    )


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    city_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cities.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Printer config: {"mode": "pdf"|"escpos", "host": ..., "port": 9100, ...}
    print_config: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONType), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    city: Mapped["City"] = relationship(back_populates="branches")


# --------------------------------------------------------------------------
# Clients & repairs
# --------------------------------------------------------------------------
class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32), index=True)
    phone_norm: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    consent_pdn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_storage_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    repairs: Mapped[list["Repair"]] = relationship(back_populates="client")


class Repair(Base, TimestampMixin):
    __tablename__ = "repairs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    city_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cities.id"), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("branches.id"), nullable=True, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clients.id"), index=True)

    device_type: Mapped[str] = mapped_column(String(32))
    brand: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(128), nullable=True)

    complectation: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONType), nullable=True
    )
    fault_client: Mapped[str | None] = mapped_column(Text, nullable=True)
    fault_master: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Согласие клиента на диагностику/ремонт (фиксируем дату).
    consent_repair_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    accepted_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    master_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(64), default="Принято", index=True)
    eta_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eta_source: Mapped[str | None] = mapped_column(String(16), nullable=True)

    price_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_final: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Что починили — комментарий мастера для бланка
    # (Düzedilen (Düzedilmedik) enjamyn görkezmesi).
    work_done: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Гарантия на ремонт (Kepillik), напр. «3 aý» / «90 дней».
    warranty_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Расходы (себестоимость) — сколько потратили на ремонт.
    cost_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Сколько выплачено мастерам по этому ремонту (заводится вручную).
    master_payout: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Отметка «оплачено» оператором при оформлении починки.
    paid: Mapped[bool] = mapped_column(Boolean, default=False)

    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    storage_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    print_count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default=RepairSource.WALKIN.value)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )

    # Второй контакт по ремонту (напр. владелец техники ≠ тот, кто доставил).
    contact2_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact2_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Заказ доставлен курьером / забран с адреса (не принесён лично в сервис).
    is_delivery: Mapped[bool] = mapped_column(Boolean, default=False)

    client: Mapped["Client"] = relationship(back_populates="repairs")
    accepted_by_user: Mapped["User"] = relationship(foreign_keys=[accepted_by])
    # Основной мастер (для совместимости: фильтры, доска, права доступа).
    master: Mapped["User | None"] = relationship(foreign_keys=[master_id])
    # Все мастера, работающие над ремонтом (Inžiner 1..4 в бланке).
    masters: Mapped[list["RepairMaster"]] = relationship(
        back_populates="repair",
        cascade="all, delete-orphan",
        order_by="RepairMaster.position",
    )
    part_orders: Mapped[list["RepairPartOrder"]] = relationship(
        back_populates="repair",
        cascade="all, delete-orphan",
        order_by="RepairPartOrder.created_at",
    )
    events: Mapped[list["RepairEvent"]] = relationship(
        back_populates="repair", cascade="all, delete-orphan", order_by="RepairEvent.created_at"
    )

    __table_args__ = (
        Index("ix_repairs_status_city", "status", "city_id"),
    )


class RepairEvent(Base, TimestampMixin):
    __tablename__ = "repair_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    repair_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repairs.id"), index=True
    )
    type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    data: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONType), nullable=True
    )

    repair: Mapped["Repair"] = relationship(back_populates="events")


class RepairMaster(Base, TimestampMixin):
    """Мастера, назначенные на ремонт (в бланке — строки «1..4 Inžiner»)."""

    __tablename__ = "repair_masters"
    __table_args__ = (
        UniqueConstraint("repair_id", "user_id", name="uq_repair_master"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    repair_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repairs.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    # Порядок вывода в бланке (0 — основной мастер).
    position: Mapped[int] = mapped_column(Integer, default=0)
    # "master" — основной исполнитель (position 0), "helper" — помощник,
    # в бланке печатается как «Inžiner (kömekçi)».
    kind: Mapped[str] = mapped_column(String(16), default="master")

    repair: Mapped["Repair"] = relationship(back_populates="masters")
    user: Mapped["User"] = relationship()


class RepairPhoto(Base, TimestampMixin):
    __tablename__ = "repair_photos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    repair_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("repairs.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(512))
    caption: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )


# --------------------------------------------------------------------------
# Parts / warehouse (склад запчастей)
# --------------------------------------------------------------------------
class Part(Base, TimestampMixin):
    __tablename__ = "parts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), index=True)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stock_qty: Mapped[int] = mapped_column(Integer, default=0)
    min_stock: Mapped[int] = mapped_column(Integer, default=0)
    cost_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    sell_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RepairPart(Base, TimestampMixin):
    __tablename__ = "repair_parts"
    __table_args__ = (
        UniqueConstraint("repair_id", "part_id", name="uq_repair_part"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    repair_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("repairs.id"), index=True)
    part_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("parts.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Запчасть внесена вручную (название + цена), а не выбрана со склада.
    # При удалении такую запчасть НЕ возвращаем на остаток.
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)

    part: Mapped["Part"] = relationship()


class RepairPartOrder(Base, TimestampMixin):
    """Запчасти, заказанные под конкретный ремонт.

    В бланке — раздел «Sargalan gerek bolan ätiýaçlyk şaýlary» (название + дата).
    Название свободным текстом: заказывают и то, чего ещё нет в каталоге.
    """

    __tablename__ = "repair_part_orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    repair_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repairs.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )

    repair: Mapped["Repair"] = relationship(back_populates="part_orders")


class EquipmentStatus(str, enum.Enum):
    """Жизненный цикл купленной техники на складе."""

    IN_STOCK = "in_stock"          # в наличии (целая)
    PARTIAL = "partial"            # частично разобран
    DISMANTLED = "dismantled"      # разобран (оставлен только корпус/частично)


class Equipment(Base, TimestampMixin):
    """Купленная техника на складе (скрап/доноры).

    Админ добавляет купленную технику, указывает за сколько купили и
    опционально какие комплектующие внутри. По мере разборки статус меняется:
    в наличии -> частично разобран -> разобран.
    """

    __tablename__ = "equipment"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    # Название техники, напр. «Ноутбук», «Моноблок», «Холодильник».
    name: Mapped[str] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # За сколько купили (ман.).
    purchase_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Дата покупки.
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=EquipmentStatus.IN_STOCK.value, index=True
    )
    # Какие комплектующие есть внутри (опционально), напр. ["Матрица", "Блок питания"].
    # Отдельный экземпляр JSON-типа (as_mutable регистрирует слушатели на самом
    # объекте типа — см. комментарий у User.extra_roles).
    components: Mapped[list | None] = mapped_column(
        MutableList.as_mutable(JSON().with_variant(JSONB(), "postgresql")), nullable=True
    )
    # Где лежит (напр. «Склад, полка 3»).
    storage_place: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------
# Payments / касса
# --------------------------------------------------------------------------
class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    repair_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("repairs.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(16), default="cash")  # cash|card|transfer
    operator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    repair: Mapped["Repair"] = relationship()
    operator: Mapped["User | None"] = relationship(foreign_keys=[operator_id])


class ComplectationItem(Base, TimestampMixin):
    __tablename__ = "complectation_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------
class PriceItem(Base, TimestampMixin):
    __tablename__ = "price_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    model_or_line: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fault: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("cities.id"), nullable=True, index=True
    )
    price_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_avg: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    typical_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------
class ChatChannel(Base, TimestampMixin):
    __tablename__ = "chat_channels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16), default="public")  # public | direct

    members: Mapped[list["ChatChannelMember"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class ChatChannelMember(Base, TimestampMixin):
    __tablename__ = "chat_channel_members"
    __table_args__ = (
        UniqueConstraint("channel_id", "user_id", name="uq_channel_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    channel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_channels.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    # Когда пользователь последний раз читал канал — для счётчика непрочитанного.
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    channel: Mapped["ChatChannel"] = relationship(back_populates="members")


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_channels.id"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    repair_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)  # repair number
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    author: Mapped["User"] = relationship(foreign_keys=[author_id])


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    repair_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("repairs.id"), nullable=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------
class PrintJob(Base, TimestampMixin):
    __tablename__ = "print_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    repair_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("repairs.id"), nullable=True, index=True
    )
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONType), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|sent|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("branches.id"), nullable=True, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PrintTemplate(Base, TimestampMixin):
    __tablename__ = "print_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)  # Jinja2/Handlebars template (not hardcoded)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------
# Settings / audit / AI
# --------------------------------------------------------------------------
class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONType), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONType), nullable=True
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AIRun(Base, TimestampMixin):
    __tablename__ = "ai_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    kind: Mapped[str] = mapped_column(String(32))
    input: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSONType), nullable=True)
    output: Mapped[dict | None] = mapped_column(MutableDict.as_mutable(JSONType), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
