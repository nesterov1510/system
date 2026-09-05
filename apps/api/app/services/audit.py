"""Журнал аудита (`audit_log`).

Модель существовала с самого начала, но не писалась ни разу. Для системы,
где есть касса, цены, выплаты мастерам и удаление ремонтов, журнал действий
обязателен: `repair_events` не подходит, потому что удаляется вместе с
ремонтом (см. DELETE /repairs/{id}).

Запись аудита НИКОГДА не должна ронять основной запрос — поэтому все ошибки
глотаются и логируются.
"""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog

log = logging.getLogger("msb.audit")

# Действия, которые обязаны попадать в журнал.
ACTION_PAYMENT_ADD = "payment.add"
ACTION_PAYMENT_DELETE = "payment.delete"
ACTION_REPAIR_FINANCE = "repair.finance"
ACTION_REPAIR_DELETE = "repair.delete"
ACTION_REPAIR_STATUS = "repair.status"
ACTION_REPAIR_ASSIGN = "repair.assign"
ACTION_REPAIR_DEVICE = "repair.device"
ACTION_PART_ADD = "part.add"
ACTION_PART_REMOVE = "part.remove"
ACTION_CLIENT_DELETE = "client.delete"
ACTION_CLIENT_MERGE_BLOCKED = "client.merge_blocked"
ACTION_USER_CREATE = "user.create"
ACTION_USER_UPDATE = "user.update"
ACTION_USER_DEACTIVATE = "user.deactivate"
ACTION_SETTING_UPDATE = "setting.update"
ACTION_PRINT_FAILURE = "print.failure"
ACTION_SMS_SENT = "sms.sent"
ACTION_LOGIN = "auth.login"


async def record(
    db: AsyncSession,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    meta: dict | None = None,
    ip: str | None = None,
    commit: bool = False,
) -> None:
    """Записать строку аудита.

    `commit=False` (по умолчанию) — запись добавляется в текущую транзакцию
    вызывающего кода и уходит в БД вместе с основным изменением. Это важно:
    аудит не должен «опережать» откатившуюся операцию.
    """
    try:
        db.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                entity=entity,
                entity_id=str(entity_id) if entity_id is not None else None,
                meta=meta,
                ip=ip,
            )
        )
        if commit:
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — аудит не должен ломать операцию
        log.warning("audit record failed (%s): %s", action, exc)


def client_ip(request) -> str | None:
    """IP клиента с учётом заголовка от обратного прокси."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for") if request.headers else None
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None
