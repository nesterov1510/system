"""Страницы входа и выхода (cookie-сессия)."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from app.db.models import User
from app.db.session import async_session_factory
from app.webui.deps import (
    clear_auth_cookies,
    get_web_user,
    set_auth_cookies,
)
from app.webui.templating import render_async

router = APIRouter(tags=["webui-auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    webuser = await get_web_user(request)
    if webuser.authenticated:
        return RedirectResponse("/repairs", status_code=303)
    html = await render_async(
        "login.html", user=None, next_url=request.query_params.get("next", "/repairs"),
        error=None,
    )
    return HTMLResponse(html)


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_url: str = Form("/repairs"),
):
    async with async_session_factory() as db:
        row = await db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        user = row.scalar_one_or_none()
        ok = user is not None and user.active and verify_password(password, user.password_hash)

    if not ok:
        html = await render_async(
            "login.html", user=None, next_url=next_url,
            error="Неверный email или пароль",
        )
        return HTMLResponse(html, status_code=401)

    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token(str(user.id))
    safe_next = next_url if next_url.startswith("/") else "/repairs"
    resp = RedirectResponse(safe_next, status_code=303)
    set_auth_cookies(resp, access, refresh)
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    clear_auth_cookies(resp)
    return resp
