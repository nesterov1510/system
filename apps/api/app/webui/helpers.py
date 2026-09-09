"""Вспомогательные функции веб-интерфейса: общий контекст шаблонов."""
from fastapi import Request

from app.webui.catalog import can_view, visible_admin_nav, visible_nav
from app.webui.deps import WebUser


async def base_context(request: Request, webuser: WebUser, **extra) -> dict:
    """Контекст, доступный каждому шаблону страницы."""
    unread = 0
    notif_unread = 0
    nav = []
    admin_nav = []
    is_admin = False
    if webuser.authenticated:
        nav = visible_nav(webuser.user)
        admin_nav = visible_admin_nav(webuser.user)
        is_admin = "admin" in webuser.user.roles
        # Считаем непрочитанные сообщения и уведомления для бейджей.
        from sqlalchemy import func, select

        from app.db.models import (
            ChatChannel,
            ChatChannelMember,
            ChatMessage,
            Notification,
        )
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            notif_unread = (
                await db.execute(
                    select(func.count(Notification.id)).where(
                        Notification.user_id == webuser.user.id,
                        Notification.read_at.is_(None),
                    )
                )
            ).scalar() or 0
            mems = (
                await db.execute(
                    select(ChatChannelMember.channel_id).where(
                        ChatChannelMember.user_id == webuser.user.id
                    )
                )
            ).scalars().all()
            if mems:
                chans = (
                    await db.execute(
                        select(ChatChannel.id, ChatChannelMember.last_read_at)
                        .join(ChatChannelMember, ChatChannelMember.channel_id == ChatChannel.id)
                        .where(
                            ChatChannel.id.in_(mems),
                            ChatChannelMember.user_id == webuser.user.id,
                        )
                    )
                ).all()
                for _cid, last_read in chans:
                    q = select(func.count()).where(
                        ChatMessage.channel_id == _cid,
                        ChatMessage.author_id != webuser.user.id,
                    )
                    if last_read is not None:
                        q = q.where(ChatMessage.created_at > last_read)
                    unread += (await db.execute(q)).scalar() or 0

    ctx = {
        "request": request,
        "user": webuser,
        "nav": nav,
        "admin_nav": admin_nav,
        # Функция для {% if can_view_nav('/chat') %} в шаблоне рейла/меню.
        "can_view_nav": lambda href: can_view(webuser.user, href),
        "is_admin_nav": is_admin,
        "unread": unread,
        "notif_unread": notif_unread,
        "flash": extra.pop("flash", None),
        "active": extra.pop("active", ""),
    }
    ctx.update(extra)
    return ctx
