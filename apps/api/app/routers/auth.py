import uuid

import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.db.models import User
from app.schemas.auth import LoginRequest, MeResponse, RefreshRequest, TokenResponse

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
