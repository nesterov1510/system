import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.db.models import Notification
from app.db.base import utcnow

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(db: DbSession, user: CurrentUser, unread_only: bool = False):
    q = select(Notification).where(Notification.user_id == user.id).order_by(
        Notification.created_at.desc()
    )
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    row = await db.execute(q.limit(100))
    return row.scalars().all()


@router.post("/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, db: DbSession, user: CurrentUser):
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        return {"ok": False}
    n.read_at = utcnow()
    await db.commit()
    return {"ok": True}
