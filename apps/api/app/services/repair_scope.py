"""Область видимости ремонтов для мастера.

Мастер (только роль `master`, без старших ролей) видит:
* свои ремонты — назначенные напрямую (`Repair.master_id`) или через список
  исполнителей (`repair_masters`, в том числе как помощник);
* свободные ремонты — без исполнителя, чтобы взять заказ себе.

Чужие ремонты, у которых уже есть исполнитель, мастеру не показываются ни в
списке «Все ремонты», ни в счётчиках этапов, ни в карточке.

Условия вынесены сюда, чтобы список, доска, бейджи этапов и сводка по деньгам
фильтровались одинаково и не разъезжались.
"""
import uuid

from sqlalchemy import and_, or_, select

from app.db.models import Repair, RepairMaster


def assigned_to(user_id: uuid.UUID):
    """Ремонт назначен мастеру напрямую или через список исполнителей."""
    subq = select(RepairMaster.repair_id).where(RepairMaster.user_id == user_id)
    return or_(Repair.master_id == user_id, Repair.id.in_(subq))


def unassigned():
    """Свободный ремонт: исполнителя нет ни в `master_id`, ни в списке."""
    return and_(
        Repair.master_id.is_(None),
        Repair.id.not_in(select(RepairMaster.repair_id)),
    )


def master_visible(user_id: uuid.UUID):
    """Что видит мастер: свои ремонты + свободные (взять себе)."""
    return or_(assigned_to(user_id), unassigned())


def is_unassigned(repair) -> bool:
    """Свободен ли ремонт (для проверок по уже загруженному объекту)."""
    if repair.master_id is not None:
        return False
    return not list(getattr(repair, "masters", None) or [])
