"""Idempotent seed: default admin, org structure, roles, channels, settings."""
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import (
    Branch,
    ChatChannel,
    City,
    Client,
    ComplectationItem,
    PriceItem,
    PrintTemplate,
    Repair,
    Setting,
    User,
    UserRole,
)
from app.services.numbering import new_public_token, normalize_phone
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

    # --- Seed price items (прайс) — демо-данные, правятся через админку ---
    row = await db.execute(select(PriceItem))
    if row.scalars().first() is None:
        demo_prices = [
            ("ТВ", "Samsung", None, "не включается", 3500, 6000, 4500, 5),
            ("ТВ", "Samsung", None, "нет изображения", 3000, 5000, 4000, 4),
            ("ТВ", "LG", None, "подсветка", 5000, 9000, 7000, 6),
            ("Монитор", "LG", None, "нет изображения", 2500, 4500, 3500, 4),
            ("Аудио", None, None, "не включается", 1500, 3000, 2200, 3),
            ("ТВ", None, None, "диагностика", 500, 1000, 800, 1),
        ]
        for dt, br, ml, fault, pmin, pmax, pavg, days in demo_prices:
            db.add(
                PriceItem(
                    device_type=dt,
                    brand=br,
                    model_or_line=ml,
                    fault=fault,
                    city_id=city.id,
                    price_min=pmin,
                    price_max=pmax,
                    price_avg=pavg,
                    typical_days=days,
                    source="seed",
                )
            )

    # --- Demo completed repairs (для дашборда «курс ремонта» и AI) ---
    row = await db.execute(
        select(Repair).where(Repair.ready_at.isnot(None)).limit(1)
    )
    if row.scalars().first() is None:
        await _seed_demo_repairs(db, city, branch)

    await db.commit()


async def _seed_demo_repairs(db, city, branch) -> None:
    """Populate a handful of closed repairs so stats/AI have data."""
    rng = random.Random(42)
    masters = (await db.execute(select(User).where(User.role == UserRole.MASTER.value))).scalars().all()
    if not masters:
        return
    master = masters[0]

    demo = [
        ("ТВ", "Samsung", "не включается", 5200, 6),
        ("ТВ", "Samsung", "подсветка", 7600, 7),
        ("ТВ", "Samsung", "не включается", 4800, 5),
        ("ТВ", "LG", "нет изображения", 6900, 8),
        ("ТВ", "LG", "подсветка", 8100, 9),
        ("ТВ", "Samsung", "не включается", 5300, 6),
        ("Монитор", "LG", "нет изображения", 3400, 4),
        ("Монитор", "LG", "не включается", 3600, 5),
        ("Монитор", "Samsung", "нет изображения", 3800, 4),
        ("Аудио", None, "не включается", 2100, 3),
        ("ТВ", "Samsung", "подсветка", 7400, 7),
        ("ТВ", "LG", "не включается", 6100, 6),
    ]

    now = datetime.now(timezone.utc)
    for i, (dt, brand, fault, price, days) in enumerate(demo):
        accepted = now - timedelta(days=rng.randint(30, 120))
        ready = accepted + timedelta(days=days)
        phone = f"+7900{100000 + i}"
        phone_norm = normalize_phone(phone)
        client = Client(full_name=f"Клиент {i+1}", phone=phone, phone_norm=phone_norm)
        db.add(client)
        await db.flush()

        from app.services.numbering import next_repair_number

        number = await next_repair_number(db, city, dt)
        db.add(
            Repair(
                number=number,
                public_token=new_public_token(),
                city_id=city.id,
                branch_id=branch.id,
                client_id=client.id,
                device_type=dt,
                brand=brand,
                model=None,
                serial=f"SN{i:04d}",
                fault_client=fault,
                accepted_by=master.id,
                master_id=master.id,
                status="Выдано",
                eta_days=days,
                eta_source="stats",
                price_final=price,
                accepted_at=accepted,
                ready_at=ready,
                issued_at=ready + timedelta(days=1),
                storage_until=ready + timedelta(days=90),
                source="walkin",
            )
        )
