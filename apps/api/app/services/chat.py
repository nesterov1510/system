"""Chat helpers: repair-number mention parsing + direct-channel helpers."""
import re
import uuid

from sqlalchemy import select

from app.db.models import ChatChannel, ChatChannelMember, ChatMessage
from app.ws.manager import manager

# Matches full numbers like TV-MSK-2026-01482 and short refs like #TV-MSK-01482
REPAIR_NUMBER_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{2,4})-([A-Z]{2,4})-(\d{4})-(\d{5})(?![A-Z0-9])"
)
SHORT_REF_RE = re.compile(r"#([A-Z]{2,4})-([A-Z]{2,4})-(\d{5})\b")


def extract_repair_ref(text: str) -> str | None:
    """Return the first repair reference found in the message text."""
    m = REPAIR_NUMBER_RE.search(text) or SHORT_REF_RE.search(text)
    return m.group(0).lstrip("#") if m else None


def dm_slug(a: uuid.UUID, b: uuid.UUID) -> str:
    return "dm-" + "-".join(sorted([str(a), str(b)]))


async def ensure_direct_channel(db, user_a_id: uuid.UUID, user_b_id: uuid.UUID):
    """Вернуть (channel, peer_name) для личного чата двух пользователей,
    создав канал при необходимости."""
    slug = dm_slug(user_a_id, user_b_id)
    row = await db.execute(select(ChatChannel).where(ChatChannel.slug == slug))
    channel = row.scalar_one_or_none()
    if channel is None:
        channel = ChatChannel(
            slug=slug, name="direct", kind="direct"
        )
        db.add(channel)
        await db.flush()
        db.add_all(
            [
                ChatChannelMember(channel_id=channel.id, user_id=user_a_id),
                ChatChannelMember(channel_id=channel.id, user_id=user_b_id),
            ]
        )
    return channel


async def _channel_member_ids(db, channel_id) -> list[uuid.UUID]:
    row = await db.execute(
        select(ChatChannelMember.user_id).where(
            ChatChannelMember.channel_id == channel_id
        )
    )
    return list(row.scalars().all())


async def send_assignment_notice(db, *, actor, master, repair):
    """Личное сообщение мастеру о том, что его назначили на ремонт.

    actor  — User (кто назначает: админ/оператор/менеджер)
    master — User (назначенный мастер)
    repair — Repair
    """
    channel = await ensure_direct_channel(db, actor.id, master.id)

    device = " · ".join(
        filter(None, [repair.brand, repair.model])
    ) or repair.device_type
    text = (
        f"🔧 {actor.name} назначил(а) вас на ремонт: "
        f"{repair.device_type} {device} · #{repair.number}"
    )

    message = ChatMessage(
        channel_id=channel.id,
        author_id=actor.id,
        text=text,
        repair_ref=repair.number,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    preview = {
        "id": str(repair.id),
        "number": repair.number,
        "status": repair.status,
        "device_type": repair.device_type,
        "brand": repair.brand,
        "model": repair.model,
    }
    payload = {
        "id": str(message.id),
        "channel_id": str(channel.id),
        "text": message.text,
        "repair_ref": message.repair_ref,
        "created_at": message.created_at.isoformat(),
        "author": {"id": str(actor.id), "name": actor.name, "role": actor.role},
        "repair_preview": preview,
    }
    ids = [actor.id, master.id]
    await manager.send_to_users(
        ids,
        {"type": "chat.message", "channel_id": str(channel.id), "message": payload},
    )
    return message

