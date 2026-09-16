"""Область видимости ремонтов для мастера.

Мастер (только роль `master`, без старших ролей) видит:

1. **свои** ремонты — где он исполнитель (назначен напрямую через
   `Repair.master_id` или через список `repair_masters`, в том числе как
   помощник) **или** он сам принял технику (`Repair.accepted_by`);
2. **свободные** — которые можно взять себе: исполнитель не назначен, принял
   не мастер (приёмка оператора/админа или публичная приёмка), и ремонт ещё не
   завершён и не выдан.

Что намеренно НЕ видно мастеру:

* чужие ремонты с назначенным исполнителем;
* чужая приёмка без исполнителя — её принял другой мастер, она уже занята им
  (он же печатает на неё этикетку, см. `permissions.can_print`);
* завершённые и выданные ремонты без исполнителя — брать там нечего.

Условия вынесены сюда, чтобы список «Все ремонты», доска, бейджи этапов и
сводка по деньгам фильтровались одинаково и не разъезжались.
"""
import uuid

from sqlalchemy import and_, not_, or_, select

from app.db.models import Repair, RepairMaster, RepairStatus, User, UserRole


def assigned_to(user_id: uuid.UUID):
    """Ремонт назначен мастеру напрямую или через список исполнителей."""
    subq = select(RepairMaster.repair_id).where(RepairMaster.user_id == user_id)
    return or_(Repair.master_id == user_id, Repair.id.in_(subq))


def own(user_id: uuid.UUID):
    """Свои ремонты: исполнитель (в т.ч. помощник) либо собственная приёмка."""
    return or_(assigned_to(user_id), Repair.accepted_by == user_id)


def _accepted_by_master():
    """Ремонт принят пользователем, чья основная роль — мастер."""
    return Repair.accepted_by.in_(
        select(User.id).where(User.role == UserRole.MASTER.value)
    )


def free_to_take():
    """Свободный ремонт — тот, который мастер вправе взять себе.

    Исполнителя нет, принял не мастер (значит это приёмка оператора/админа или
    публичной приёмки, ушедшая в общую очередь), и ремонт не завершён и не выдан.
    """
    return and_(
        Repair.master_id.is_(None),
        Repair.id.not_in(select(RepairMaster.repair_id)),
        not_(_accepted_by_master()),
        Repair.status != RepairStatus.DONE,
        Repair.issued_at.is_(None),
    )


def master_visible(user_id: uuid.UUID):
    """Что видит мастер: свои ремонты + свободные (взять себе)."""
    return or_(own(user_id), free_to_take())
