"""Call-center queue: согласовать цену / сказать «готово» / просрочка хранения."""
import uuid


from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require_roles
from app.db.models import Repair, UserRole
from app.routers.repairs import _serialize

router = APIRouter(prefix="/callcenter", tags=["callcenter"])


async def _queue(db, kind: str, limit: int):
    from app.db.base import utcnow

    now = utcnow()
    q = select(Repair).options(selectinload(Repair.client), selectinload(Repair.events))

    if kind == "agree":
        # Нужно позвонить клиенту для согласования цены.
        q = q.where(Repair.status == "Согласование")
    elif kind == "ready":
        # Сказать, что готово.
        q = q.where(Repair.status == "Готово к выдаче")
    elif kind == "overdue":
        # Просрочка хранения (не выдано и срок вышел).
        q = q.where(
            Repair.storage_until.isnot(None),
            Repair.storage_until < now,
            Repair.status.notin_(["Выдано", "Отказ", "Архив"]),
        )
    else:
        # "all": всё активное, кроме закрытого.
        q = q.where(Repair.status.notin_(["Выдано", "Отказ", "Архив"]))

    q = q.order_by(Repair.accepted_at.desc()).limit(limit)
    row = await db.execute(q)
    return [_serialize(r) for r in row.scalars().all()]


@router.get("/queue")
async def callcenter_queue(
    db: DbSession,
    user: CurrentUser,
    kind: str = Query("all", pattern="^(agree|ready|overdue|all)$"),
    limit: int = Query(100, le=200),
):
    # admin + operator can view the queue (callcenter role removed; operator
    # takes over everything except analytics).
    if user.role not in (UserRole.ADMIN.value, UserRole.OPERATOR.value):
        # Masters/operators still can list their repairs via /repairs.
        from fastapi import HTTPException

        raise HTTPException(403, "Недостаточно прав для очереди call-центра")
    return await _queue(db, kind, limit)
