"""Страница чата. Realtime — существующий WebSocket /ws (авторизация по
httpOnly-cookie), история и отправка — функции API-роутера чата."""
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db.models import ChatChannel
from app.db.session import async_session_factory
from app.routers import chat as chat_api
from app.webui.deps import bound_user, get_web_user
from app.webui.helpers import base_context
from app.webui.templating import render_async

router = APIRouter(tags=["webui-chat"])


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, channel: uuid.UUID | None = None):
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login", status_code=303)
    db = async_session_factory()
    user = await bound_user(db, webuser)
    if user is None:
        await db.close()
        return RedirectResponse("/login", status_code=303)
    try:
        channels = await chat_api.list_channels(db, user)
        users = await chat_api.list_users(db, user)

        current = None
        messages = []
        if channel:
            try:
                messages = await chat_api.list_messages(channel, db, user, 100)
                current = await db.get(ChatChannel, channel)
            except Exception:
                channel = None
        # По умолчанию — первый доступный канал.
        if channel is None and channels:
            first = channels[0]
            channel = first.id
            messages = await chat_api.list_messages(first.id, db, user, 100)
            current = await db.get(ChatChannel, first.id)

        ctx = await base_context(
            request, webuser, active="/chat",
            channels=channels, users=users, messages=messages,
            current_id=str(channel) if channel else None,
            current_name=(current.name if current else None),
            me_id=str(user.id),
        )
        html = await render_async("chat.html", **ctx)
        return HTMLResponse(html)
    finally:
        await db.close()


@router.post("/chat/send")
async def chat_send(request: Request):
    """Отправка сообщения обычной HTML-формой (PRG) — без fetch/JSON в браузере."""
    from app.schemas.chat import MessageCreate

    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    channel_id = form.get("channel_id")
    text = (form.get("text") or "").strip()
    try:
        channel_uuid = uuid.UUID(channel_id)
    except (TypeError, ValueError):
        return RedirectResponse("/chat", status_code=303)
    db = async_session_factory()
    try:
        me = await bound_user(db, webuser)
        if me is None:
            return RedirectResponse("/login", status_code=303)
        if text:
            await chat_api.create_message(
                channel_uuid, MessageCreate(text=text), db, me
            )
        return RedirectResponse(f"/chat?channel={channel_uuid}", status_code=303)
    finally:
        await db.close()


@router.post("/chat/direct/{user_id}")
async def chat_open_direct(request: Request, user_id: uuid.UUID):
    """Найти/создать личный чат с сотрудником и открыть его."""
    webuser = await get_web_user(request)
    if not webuser.authenticated:
        return RedirectResponse("/login", status_code=303)
    db = async_session_factory()
    try:
        me = await bound_user(db, webuser)
        if me is None:
            return RedirectResponse("/login", status_code=303)
        ch = await chat_api.open_direct(db, me, user_id)
        return RedirectResponse(f"/chat?channel={ch.id}", status_code=303)
    finally:
        await db.close()
