"""Idempotent seed: default admin, org structure, roles, channels, settings."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import (
    Branch,
    ChatChannel,
    City,
    ComplectationItem,
    Setting,
    User,
    UserRole,
)
from app.services.settings import DEFAULT_SETTINGS


async def seed(db: AsyncSession) -> None:
    # --- Settings ---
    for key, meta in DEFAULT_SETTINGS.items():
        row = await db.execute(select(Setting).where(Setting.key == key))
        if row.scalar_one_or_none() is None:
            db.add(
                Setting(key=key, value=meta["value"], description=meta["description"])
            )

    # --- City ---
    row = await db.execute(select(City).where(City.slug == "msk"))
    city = row.scalar_one_or_none()
    if city is None:
        city = City(slug="msk", name="Москва", timezone="Europe/Moscow")
        db.add(city)
        await db.flush()

    # --- Branch ---
    row = await db.execute(select(Branch).where(Branch.name == "Центральная точка"))
    branch = row.scalar_one_or_none()
    if branch is None:
        branch = Branch(
            city_id=city.id,
            name="Центральная точка",
            address="г. Москва, ул. Примерная, 1",
            phone="+7 495 000-00-00",
            # Epson EcoTank L3250 = A4 inkjet via OS driver -> mode "pdf"
            print_config={"mode": "pdf", "paper": "A4"},
        )
        db.add(branch)
        await db.flush()

    # --- Users ---
    demo_users = [
        {
            "name": "Администратор",
            "email": settings.SEED_ADMIN_EMAIL,
            "password": settings.SEED_ADMIN_PASSWORD,
            "phone": settings.SEED_ADMIN_PHONE,
            "role": UserRole.ADMIN.value,
        },
        {
            "name": "Оператор Анна",
            "email": "operator@remontflow.local",
            "password": "operator123",
            "phone": "+70000000001",
            "role": UserRole.OPERATOR.value,
        },
        {
            "name": "Мастер Сергей",
            "email": "master@remontflow.local",
            "password": "master123",
            "phone": "+70000000002",
            "role": UserRole.MASTER.value,
        },
        {
            "name": "Оператор КЦ Мария",
            "email": "call@remontflow.local",
            "password": "call123",
            "phone": "+70000000003",
            "role": UserRole.CALLCENTER.value,
        },
        {
            "name": "Менеджер Иван",
            "email": "manager@remontflow.local",
            "password": "manager123",
            "phone": "+70000000004",
            "role": UserRole.MANAGER.value,
        },
    ]
    for u in demo_users:
        row = await db.execute(select(User).where(User.email == u["email"]))
        if row.scalar_one_or_none() is None:
            db.add(
                User(
                    name=u["name"],
                    email=u["email"],
                    phone=u["phone"],
                    password_hash=hash_password(u["password"]),
                    role=u["role"],
                    city_id=city.id,
                    branch_id=branch.id,
                )
            )

    # --- Chat channels ---
    channels = [
        ("obshchiy", "#общий"),
        ("priemka", "#приёмка"),
        ("mastera", "#мастера"),
        ("callcenter", "#callcenter"),
    ]
    for slug, name in channels:
        row = await db.execute(select(ChatChannel).where(ChatChannel.slug == slug))
        if row.scalar_one_or_none() is None:
            db.add(ChatChannel(slug=slug, name=name, kind="public"))

    # --- Complectation items ---
    items = ["ПДУ", "Кабель питания", "Подставка", "Документы", "Аккумулятор"]
    for i, name in enumerate(items):
        row = await db.execute(
            select(ComplectationItem).where(ComplectationItem.name == name)
        )
        if row.scalar_one_or_none() is None:
            db.add(ComplectationItem(name=name, sort=i))

    await db.commit()
