"""Оплаты / касса: платежи по ремонту, методы, остаток.

Доступ к кассе ограничен ролями (`core.permissions`): раньше принять платёж
мог любой аутентифицированный пользователь, включая мастера, который ведёт
ремонт. Сумма в событии ремонта форматируется символом валюты из настроек
(TMT, «ман.»), а не захардкоженным знаком рубля.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require_roles
from app.core.permissions import (
    CASHIER_ROLES,
    can_refund_payment,
    can_take_payment,
)
from app.db.models import Payment, Repair, RepairEvent, UserRole
from app.schemas.payments import PaymentCreate, PaymentOut
from app.services import audit
from app.services.settings import get_currency

router = APIRouter(tags=["payments"])

CanRefund = require_roles(UserRole.ADMIN.value, UserRole.MANAGER.value)
CanTakePayment = require_roles(*CASHIER_ROLES)


async def _currency_symbol(db) -> str:
    """Символ валюты из настроек (по умолчанию туркменский манат)."""
    currency = await get_currency(db)
    return str(currency.get("symbol") or "ман.").strip()


def _fmt_amount(amount, symbol: str) -> str:
    """1234.5 -> «1234.50 ман.» (разделитель тысяч — пробел, как в бланке)."""
    try:
        return f"{float(amount):,.2f}".replace(",", " ") + f" {symbol}"
    except (TypeError, ValueError):
        return f"{amount} {symbol}"


@router.get("/repairs/{repair_id}/payments", response_model=list[PaymentOut])
async def list_payments(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    repair = await db.get(Repair, repair_id)
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    row = await db.execute(
        select(Payment).where(Payment.repair_id == repair_id).order_by(Payment.paid_at)
    )
    return row.scalars().all()


@router.post("/repairs/{repair_id}/payments", response_model=PaymentOut, status_code=201)
async def add_payment(
    repair_id: uuid.UUID,
    payload: PaymentCreate,
    db: DbSession,
    user: CurrentUser,
    _: bool = Depends(CanTakePayment),
):
    """Принять платёж. Только кассовые роли (админ/менеджер/оператор)."""
    repair = await db.get(Repair, repair_id)
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    if not can_take_payment(user):  # страховка: зависимость уже проверила роль
        raise HTTPException(403, "Принимать платежи может администратор, менеджер или оператор")

    payment = Payment(
        repair_id=repair_id,
        amount=payload.amount,
        method=payload.method,
        operator_id=user.id,
    )
    db.add(payment)
    symbol = await _currency_symbol(db)
    db.add(
        RepairEvent(
            repair_id=repair_id,
            type="price",
            actor_id=user.id,
            data={
                "message": (
                    f"Оплата {_fmt_amount(payload.amount, symbol)} ({payload.method})"
                )
            },
        )
    )
    # Касса — материально значимая операция: пишем в журнал аудита.
    await audit.record(
        db,
        audit.ACTION_PAYMENT_ADD,
        actor_id=user.id,
        entity="repair",
        entity_id=repair_id,
        meta={
            "amount": float(payload.amount),
            "method": payload.method,
            "currency": (await get_currency(db)).get("code"),
        },
    )
    await db.commit()
    await db.refresh(payment)
    return payment


@router.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    _: bool = Depends(CanRefund),
):
    """Сторнировать платёж. Только админ/менеджер."""
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(404, "Платёж не найден")
    if not can_refund_payment(user):
        raise HTTPException(403, "Отменять платёж может администратор или менеджер")

    symbol = await _currency_symbol(db)
    db.add(
        RepairEvent(
            repair_id=payment.repair_id,
            type="price",
            actor_id=user.id,
            data={"message": f"Платёж отменён: {_fmt_amount(payment.amount, symbol)}"},
        )
    )
    await audit.record(
        db,
        audit.ACTION_PAYMENT_DELETE,
        actor_id=user.id,
        entity="repair",
        entity_id=payment.repair_id,
        meta={
            "payment_id": str(payment.id),
            "amount": float(payment.amount),
            "method": payment.method,
        },
    )
    await db.delete(payment)
    await db.commit()
    return {"ok": True}
