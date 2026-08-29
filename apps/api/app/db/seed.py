"""Idempotent seed: только минимально необходимое для старта.
Создаётся:
  - город (Ашхабад)
  - филиал (Центральная точка)
  - admin (admin@msb.local)
  - чат-каналы (#общий, #приёмка, #мастера, #callcenter)
  - комплектация (пульт, шнур и т.д.)
  - шаблон бланка
  - настройки (срок хранения и пр.)

Без демо-данных: ремонтов, клиентов, запчастей, прайса, лишних пользователей.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import (
    Branch,
    ChatChannel,
    City,
    ComplectationItem,
    PrintTemplate,
    Setting,
    User,
    UserRole,
)
from app.services.print import DEFAULT_TEMPLATE, template_to_body
from app.services.settings import DEFAULT_SETTINGS


async def seed(db: AsyncSession) -> None:
    # --- Settings ---
    for key, meta in DEFAULT_SETTINGS.items():
        row = await db.execute(select(Setting).where(Setting.key == key))
        if row.scalar_one_or_none() is None:
            db.add(
                Setting(key=key, value=meta["value"], description=meta["description"])
            )

    # --- City (Туркменистан, Ашхабад) ---
    row = await db.execute(select(City).where(City.slug == "asg"))
    city = row.scalar_one_or_none()
    if city is None:
        city = City(slug="asg", name="Ашхабад", timezone="Asia/Ashgabat")
        db.add(city)
        await db.flush()

    # --- Branch ---
    row = await db.execute(select(Branch).where(Branch.name == "Центральная точка"))
    branch = row.scalar_one_or_none()
    if branch is None:
        branch = Branch(
            city_id=city.id,
            name="Центральная точка",
            address="г. Ашхабад",
            phone="",
            print_config={"mode": "pdf", "paper": "A4"},
        )
        db.add(branch)
        await db.flush()

    # --- Admin user (только один) ---
    row = await db.execute(select(User).where(User.role == UserRole.ADMIN.value))
    if row.scalar_one_or_none() is None:
        if settings.ENV == "prod" and (
            not settings.SEED_ADMIN_PASSWORD
            or settings.SEED_ADMIN_PASSWORD.startswith("CHANGE_ME")
            or settings.SEED_ADMIN_PASSWORD == "admin123"
        ):
            raise RuntimeError(
                "В продакшене задайте уникальный SEED_ADMIN_PASSWORD в .env "
                "до первого запуска базы данных."
            )
        db.add(
            User(
                name="Администратор",
                email=settings.SEED_ADMIN_EMAIL,
                phone=settings.SEED_ADMIN_PHONE,
                password_hash=hash_password(settings.SEED_ADMIN_PASSWORD),
                role=UserRole.ADMIN.value,
                city_id=city.id,
                branch_id=branch.id,
            )
        )

    # --- Chat channels (обязательны для работы чата) ---
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

    # --- Complectation items (для формы приёмки) ---
    items = ["Пульт", "Шнур питания", "Ножки", "Крепление", "Документы"]
    for i, name in enumerate(items):
        row = await db.execute(
            select(ComplectationItem).where(ComplectationItem.name == name)
        )
        if row.scalar_one_or_none() is None:
            db.add(ComplectationItem(name=name, sort=i))

    # --- Default print template (бланк) ---
    row = await db.execute(select(PrintTemplate))
    if row.scalars().first() is None:
        db.add(
            PrintTemplate(
                name=DEFAULT_TEMPLATE["name"],
                body=template_to_body(DEFAULT_TEMPLATE),
                is_default=True,
            )
        )

    await db.commit()
