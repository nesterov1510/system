"""In-app notifications + push to WebSocket connections."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notification


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    type_: str,
    title: str,
    body: str | None = None,
    repair_id: uuid.UUID | None = None,
) -> Notification:
    n = Notification(
        user_id=user_id, type=type_, title=title, body=body, repair_id=repair_id
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return n
