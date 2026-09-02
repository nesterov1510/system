import uuid

import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    ProfileUpdate,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _authenticate(db, email: str, password: str) -> User:
    row = await db.execute(select(User).where(User.email == email.lower().strip()))
    user = row.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )
    if not user.active:
        raise HTTPException(status_code=403, detail="Пользователь заблокирован")
    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession):
    user = await _authenticate(db, payload.email, payload.password)
    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh, user=user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: DbSession):
    try:
        data = decode_token(payload.refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Невалидный refresh-токен")
    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Не refresh-токен")
    user = await db.get(User, uuid.UUID(data["sub"]))
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    access = create_access_token(str(user.id), user.role)
    refresh_token = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh_token, user=user)


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser):
    return user


@router.patch("/me", response_model=MeResponse)
async def update_me(payload: ProfileUpdate, db: DbSession, user: CurrentUser):
    """Обновление собственного профиля: имя, телефон, telegram, email, пароль."""
    data = payload.model_dump(exclude_unset=True)

    # Смена пароля — только при верном текущем.
    new_password = data.pop("new_password", None)
    current_password = data.pop("current_password", None)
    if new_password:
        if not current_password or not verify_password(
            current_password, user.password_hash
        ):
            raise HTTPException(status_code=400, detail="Текущий пароль неверный")
        user.password_hash = hash_password(new_password)

    # Email — с проверкой уникальности (кроме себя).
    email = data.pop("email", None)
    if email is not None:
        email = email.strip().lower()
        if email and email != user.email:
            row = await db.execute(
                select(User).where(User.email == email, User.id != user.id)
            )
            if row.scalar_one_or_none() is not None:
                raise HTTPException(status_code=409, detail="Email уже занят")
            user.email = email

    for field in ("name", "phone", "telegram"):
        if field in data:
            setattr(user, field, data[field])

    await db.commit()
    await db.refresh(user)
    return user
