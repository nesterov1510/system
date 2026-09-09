"""Зависимости веб-интерфейса: аутентификация по httpOnly-cookie.

В отличие от JSON-API (где токен в заголовке Authorization), страницы
используют access-токен, записанный в httpOnly-cookie при логине. Это убирает
хранение пароля/токена в localStorage: JS до токена не дотягивается, при
каждом запросе сервер сам проверяет подпись и тип токена.
"""
import uuid

import jwt
from fastapi import Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.models import User
from app.db.session import async_session_factory

ACCESS_COOKIE = "msb_access"
REFRESH_COOKIE = "msb_refresh"


def _decode(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return decode_token(token)
    except jwt.PyJWTError:
        return None


async def load_user(user_id: str | None) -> User | None:
    if not user_id:
        return None
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None
    async with async_session_factory() as db:
        user = await db.get(User, uid)
        if user is None or not user.active:
            return None
        # Отвязываем от сессии: свойства (roles/has_role) не требуют ленивых
        # запросов, поля скалярные — безопасно использовать после закрытия.
        db.expunge(user)
        return user


def set_auth_cookies(response, access: str, refresh: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE, access,
        httponly=True, samesite="lax", max_age=settings.ACCESS_TOKEN_TTL_MIN * 60,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh,
        httponly=True, samesite="lax", max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        path="/",
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


async def bound_user(db, webuser: "WebUser") -> User | None:
    """Привязанный к сессии `db` пользователь (persistent), а не detached-объект.

    `get_web_user`/`load_user` отвязывают пользователя от своей сессии
    (`expunge`) — это безопасно для чтения скалярных полей в шаблонах, но при
    записи (смена пароля, профиль, сообщение чата и т.п.) SQLAlchemy падает с
    «Instance … is not persistent within this Session». Перед записью всегда
    перечитываем пользователя в рабочей сессии.
    """
    if webuser is None or webuser.user is None:
        return None
    return await db.get(User, webuser.user.id)


class WebUser:
    """Текущий пользователь страницы + флаги для шаблона."""

    def __init__(self, user: User | None):
        self.user = user

    @property
    def authenticated(self) -> bool:
        return self.user is not None

    def __getattr__(self, item):
        # Прокидываем атрибуты пользователя (name, role, has_role, roles...).
        if self.user is not None:
            return getattr(self.user, item)
        raise AttributeError(item)


async def get_web_user(request: Request) -> WebUser:
    """Прочитать пользователя из cookie; при протухшем access — тихо обновить
    по refresh и подменить cookie в ответе (через request.state)."""
    access = request.cookies.get(ACCESS_COOKIE)
    refresh = request.cookies.get(REFRESH_COOKIE)

    payload = _decode(access)
    if payload and payload.get("type") == "access":
        user = await load_user(payload.get("sub"))
        if user is not None:
            return WebUser(user)

    # Access истёк/битый — пробуем refresh (тихий re-login без пароля).
    rpayload = _decode(refresh)
    if rpayload and rpayload.get("type") == "refresh":
        user = await load_user(rpayload.get("sub"))
        if user is not None:
            new_access = create_access_token(str(user.id), user.role)
            new_refresh = create_refresh_token(str(user.id))
            request.state.refreshed_cookies = (new_access, new_refresh)
            return WebUser(user)

    return WebUser(None)


def apply_refreshed_cookies(request: Request, response) -> None:
    """Если во время запроса access обновили по refresh — записать новый токен."""
    refreshed = getattr(request.state, "refreshed_cookies", None)
    if refreshed:
        set_auth_cookies(response, refreshed[0], refreshed[1])


def login_redirect(request: Request) -> RedirectResponse:
    next_url = request.url.path
    target = "/login"
    if next_url and next_url != "/login":
        target = f"/login?next={next_url}"
    return RedirectResponse(target, status_code=303)
