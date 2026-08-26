import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.deps import AdminOnly, CurrentUser, DbSession
from app.core.security import hash_password
from app.db.models import Branch, City, Setting, User
from app.schemas.admin import (
    BranchCreate,
    BranchOut,
    CityCreate,
    CityOut,
    SettingIn,
    SettingOut,
)
from app.schemas.user import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[AdminOnly])


# --- Cities ---
@router.get("/cities", response_model=list[CityOut])
async def list_cities(db: DbSession):
    row = await db.execute(select(City).order_by(City.name))
    return row.scalars().all()


@router.post("/cities", response_model=CityOut, status_code=201)
async def create_city(payload: CityCreate, db: DbSession):
    city = City(slug=payload.slug.lower(), name=payload.name, timezone=payload.timezone)
    db.add(city)
    await db.commit()
    await db.refresh(city)
    return city


@router.patch("/cities/{city_id}", response_model=CityOut)
async def update_city(city_id: uuid.UUID, payload: CityCreate, db: DbSession):
    city = await db.get(City, city_id)
    if city is None:
        raise HTTPException(404, "Город не найден")
    city.slug = payload.slug.lower()
    city.name = payload.name
    city.timezone = payload.timezone
    await db.commit()
    return city


# --- Branches ---
@router.get("/branches", response_model=list[BranchOut])
async def list_branches(db: DbSession):
    row = await db.execute(select(Branch).order_by(Branch.name))
    return row.scalars().all()


@router.post("/branches", response_model=BranchOut, status_code=201)
async def create_branch(payload: BranchCreate, db: DbSession):
    branch = Branch(**payload.model_dump())
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.patch("/branches/{branch_id}", response_model=BranchOut)
async def update_branch(branch_id: uuid.UUID, payload: BranchCreate, db: DbSession):
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404, "Точка не найдена")
    for field, value in payload.model_dump().items():
        setattr(branch, field, value)
    await db.commit()
    return branch


# --- Users ---
@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbSession):
    row = await db.execute(select(User).order_by(User.name))
    return row.scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, db: DbSession):
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email уже занят")
    user = User(
        name=payload.name,
        email=payload.email.lower(),
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=payload.role,
        city_id=payload.city_id,
        branch_id=payload.branch_id,
        active=payload.active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, payload: UserUpdate, db: DbSession):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for field, value in data.items():
        setattr(user, field, value)
    if password:
        user.password_hash = hash_password(password)
    await db.commit()
    return user


# --- Settings ---
@router.get("/settings", response_model=list[SettingOut])
async def list_settings(db: DbSession):
    row = await db.execute(select(Setting).order_by(Setting.key))
    return row.scalars().all()


@router.put("/settings/{key}", response_model=SettingOut)
async def upsert_setting(key: str, payload: SettingIn, db: DbSession):
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None:
        setting = Setting(key=key, value=payload.value, description=payload.description)
        db.add(setting)
    else:
        setting.value = payload.value
        setting.description = payload.description
    await db.commit()
    return setting
