from pydantic import BaseModel, Field

from app.schemas.user import UserOut


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class MeResponse(UserOut):
    pass


class ProfileUpdate(BaseModel):
    """Пользователь правит свой профиль: имя, телефон, email, telegram, пароль."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = None
    telegram: str | None = None
    email: str | None = None
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=6)
