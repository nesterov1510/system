"""Оплаты / касса: платежи по ремонту, методы, остаток."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require_roles
from app.db.models import Payment, Repair, RepairEvent, UserRole
from app.schemas.payments import PaymentCreate, PaymentOut

router = APIRouter(tags=["payments"])

CanRefund = require_roles(UserRole.ADMIN.value, UserRole.OPERATOR.value)


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
    repair_id: uuid.UUID, payload: PaymentCreate, db: DbSession, user: CurrentUser
):
    repair = await db.get(Repair, repair_id)
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")

    payment = Payment(
        repair_id=repair_id,
        amount=payload.amount,
        method=payload.method,
        operator_id=user.id,
    )
    db.add(payment)
    db.add(
        RepairEvent(
            repair_id=repair_id,
            type="price",
            actor_id=user.id,
            data={
                "message": f"Оплата {payload.amount:,.0f} ₽ ({payload.method})".replace(",", " ")
            },
        )
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
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(404, "Платёж не найден")
    db.add(
        RepairEvent(
            repair_id=payment.repair_id,
            type="price",
            actor_id=user.id,
            data={"message": f"Платёж отменён: {payment.amount:,.0f} ₽".replace(",", " ")},
        )
    )
    await db.delete(payment)
    await db.commit()
    return {"ok": True}
