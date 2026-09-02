import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.db.models import (
    ChatChannel,
    ChatChannelMember,
    ChatMessage,
    Repair,
    User,
)
from app.schemas.chat import ChannelOut, ChatUser, MessageCreate, MessageOut
from app.services.chat import dm_slug, extract_repair_ref
from app.ws.manager import manager

router = APIRouter(prefix="/chat", tags=["chat"])


async def _member(db, channel_id, user_id):
    row = await db.execute(
        select(ChatChannelMember).where(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == user_id,
        )
    )
    return row.scalar_one_or_none()


async def _unread_count(db, channel_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Сколько чужих сообщений в канале после последнего прочтения."""
    mem = await _member(db, channel_id, user_id)
    if mem is None:
        return 0
    q = select(func.count()).where(
        ChatMessage.channel_id == channel_id,
        ChatMessage.author_id != user_id,
    )
    if mem.last_read_at is not None:
        q = q.where(ChatMessage.created_at > mem.last_read_at)
    return (await db.execute(q)).scalar() or 0


async def _mark_read(db, channel_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Пометить канал прочитанным для пользователя."""
    from app.db.base import utcnow

    mem = await _member(db, channel_id, user_id)
    if mem is None:
        # Публичный канал без записи членства — создаём лениво.
        mem = ChatChannelMember(channel_id=channel_id, user_id=user_id)
        db.add(mem)
    mem.last_read_at = utcnow()


async def _repair_preview(db, number: str) -> dict | None:
    row = await db.execute(select(Repair).where(Repair.number == number))
    repair = row.scalar_one_or_none()
    if repair is None:
        # Short ref like "TV-MSK-00001" (no year) -> match prefix + seq.
        parts = number.split("-")
        if len(parts) == 3:
            prefix, city, seq = parts
            like = f"{prefix}-{city}-%-{seq}"
            row = await db.execute(select(Repair).where(Repair.number.like(like)))
            repairs = row.scalars().all()
            repair = repairs[0] if len(repairs) == 1 else None
    if repair is None:
        return None
    return {
        "id": str(repair.id),
        "number": repair.number,
        "status": repair.status,
        "device_type": repair.device_type,
        "brand": repair.brand,
        "model": repair.model,
    }


async def _channel_member_ids(db, channel_id) -> list[uuid.UUID]:
    row = await db.execute(
        select(ChatChannelMember.user_id).where(ChatChannelMember.channel_id == channel_id)
    )
    return list(row.scalars().all())


async def _require_access(db, user, channel: ChatChannel) -> None:
    """Публичный канал открыт всем; в direct — только участники."""
    if channel.kind == "direct":
        ids = await _channel_member_ids(db, channel.id)
        if user.id not in ids:
            raise HTTPException(403, "Нет доступа к этому чату")


@router.get("/unread-total")
async def unread_total(db: DbSession, user: CurrentUser):
    """Суммарное количество непрочитанных сообщений пользователя (для бейджа в меню)."""
    mine = await db.execute(
        select(ChatChannelMember.channel_id).where(ChatChannelMember.user_id == user.id)
    )
    my_ids = list(mine.scalars().all())
    total = 0
    if my_ids:
        channels = await db.execute(
            select(ChatChannel).where(
                ChatChannel.id.in_(my_ids),
                ChatChannel.kind.in_(["direct", "public"]),
            )
        )
        for c in channels.scalars().all():
            total += await _unread_count(db, c.id, user.id)
    return {"total": total}


@router.get("/users", response_model=list[ChatUser])
async def list_users(db: DbSession, user: CurrentUser):
    """Активные сотрудники (для личной переписки), кроме текущего."""
    row = await db.execute(
        select(User)
        .where(User.active.is_(True), User.id != user.id)
        .order_by(User.name)
    )
    return [
        ChatUser(id=u.id, name=u.name, role=u.role) for u in row.scalars().all()
    ]


@router.post("/direct/{user_id}", response_model=ChannelOut)
async def open_direct(db: DbSession, user: CurrentUser, user_id: uuid.UUID):
    """Найти или создать личный чат с сотрудником."""
    if user_id == user.id:
        raise HTTPException(400, "Нельзя писать самому себе")
    target = await db.get(User, user_id)
    if target is None or not target.active:
        raise HTTPException(404, "Сотрудник не найден")

    slug = dm_slug(user.id, user_id)
    row = await db.execute(select(ChatChannel).where(ChatChannel.slug == slug))
    channel = row.scalar_one_or_none()
    if channel is None:
        channel = ChatChannel(slug=slug, name="direct", kind="direct")
        db.add(channel)
        await db.flush()
        db.add_all(
            [
                ChatChannelMember(channel_id=channel.id, user_id=user.id),
                ChatChannelMember(channel_id=channel.id, user_id=user_id),
            ]
        )
        await db.commit()
    return ChannelOut(
        id=channel.id,
        slug=channel.slug,
        name=channel.name,
        kind="direct",
        peer=ChatUser(id=target.id, name=target.name, role=target.role),
        unread=0,
    )


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(db: DbSession, user: CurrentUser):
    """Каналы, доступные пользователю: публичные + его личные чаты."""
    out: list[ChannelOut] = []

    pub = await db.execute(
        select(ChatChannel)
        .where(ChatChannel.kind == "public")
        .order_by(ChatChannel.name)
    )
    for c in pub.scalars().all():
        out.append(
            ChannelOut(
                id=c.id,
                slug=c.slug,
                name=c.name,
                kind=c.kind,
                peer=None,
                unread=await _unread_count(db, c.id, user.id),
            )
        )

    mine = await db.execute(
        select(ChatChannelMember.channel_id).where(ChatChannelMember.user_id == user.id)
    )
    my_ids = list(mine.scalars().all())
    if my_ids:
        direct = await db.execute(
            select(ChatChannel)
            .where(ChatChannel.id.in_(my_ids), ChatChannel.kind == "direct")
            .order_by(ChatChannel.created_at.desc())
        )
        for c in direct.scalars().all():
            ids = await _channel_member_ids(db, c.id)
            peer_ids = [x for x in ids if x != user.id]
            peer = None
            if peer_ids:
                urow = await db.execute(select(User).where(User.id == peer_ids[0]))
                u = urow.scalar_one_or_none()
                if u is not None:
                    peer = ChatUser(id=u.id, name=u.name, role=u.role)
            out.append(
                ChannelOut(
                    id=c.id,
                    slug=c.slug,
                    name=peer.name if peer else c.name,
                    kind=c.kind,
                    peer=peer,
                    unread=await _unread_count(db, c.id, user.id),
                )
            )
    return out


@router.post("/channels/{channel_id}/read")
async def mark_read(
    channel_id: uuid.UUID, db: DbSession, user: CurrentUser
):
    """Пометить канал прочитанным для текущего пользователя."""
    channel = await db.get(ChatChannel, channel_id)
    if channel is None:
        raise HTTPException(404, "Канал не найден")
    await _mark_read(db, channel_id, user.id)
    await db.commit()
    return {"ok": True}


@router.get("/channels/{channel_id}/messages", response_model=list[MessageOut])
async def list_messages(
    channel_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(50, le=200),
    before: uuid.UUID | None = None,
):
    channel = await db.get(ChatChannel, channel_id)
    if channel is None:
        raise HTTPException(404, "Канал не найден")
    await _require_access(db, user, channel)

    q = (
        select(ChatMessage)
        .where(ChatMessage.channel_id == channel_id)
        .options(selectinload(ChatMessage.author))
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    row = await db.execute(q)
    messages = list(row.scalars().all())
    messages.reverse()

    # Чтение канала — сбрасываем счётчик непрочитанного.
    await _mark_read(db, channel_id, user.id)
    await db.commit()

    out = []
    for m in messages:
        preview = await _repair_preview(db, m.repair_ref) if m.repair_ref else None
        out.append(
            MessageOut(
                id=m.id,
                channel_id=m.channel_id,
                text=m.text,
                repair_ref=m.repair_ref,
                created_at=m.created_at,
                author={"id": m.author.id, "name": m.author.name, "role": m.author.role},
                repair_preview=preview,
            )
        )
    return out


@router.post("/channels/{channel_id}/messages", response_model=MessageOut)
async def create_message(
    channel_id: uuid.UUID,
    payload: MessageCreate,
    db: DbSession,
    user: CurrentUser,
):
    channel = await db.get(ChatChannel, channel_id)
    if channel is None:
        raise HTTPException(404, "Канал не найден")
    await _require_access(db, user, channel)

    # Auto-detect repair mention if not explicitly provided.
    repair_ref = payload.repair_ref or extract_repair_ref(payload.text)

    message = ChatMessage(
        channel_id=channel_id,
        author_id=user.id,
        text=payload.text,
        repair_ref=repair_ref,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    preview = await _repair_preview(db, repair_ref) if repair_ref else None

    out = MessageOut(
        id=message.id,
        channel_id=message.channel_id,
        text=message.text,
        repair_ref=message.repair_ref,
        created_at=message.created_at,
        author={"id": user.id, "name": user.name, "role": user.role},
        repair_preview=preview,
    )

    event = {
        "type": "chat.message",
        "channel_id": str(channel_id),
        "message": out.model_dump(mode="json"),
    }
    # В публичный канал — всем; в direct — только участникам диалога.
    if channel.kind == "direct":
        ids = await _channel_member_ids(db, channel.id)
        await manager.send_to_users(ids, event)
    else:
        await manager.broadcast(event)
    return out
