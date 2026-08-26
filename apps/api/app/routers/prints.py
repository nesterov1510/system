"""Print jobs: render PDF blank -> queue for the on-site print-agent.

The blank layout is driven by the default `print_templates` row (editable in
admin). The print-agent polls `GET /print/jobs?status=queued`, downloads the PDF
and sends it to the OS printer (Epson EcoTank L3250 via driver).
"""
import base64
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.db.models import Branch, City, PrintJob, PrintTemplate, Repair, RepairEvent
from app.services.print import body_to_template, render_blank_pdf
from app.services.settings import (
    get_consent_repair_text,
    get_currency,
    get_legal_text,
    get_printer,
)

router = APIRouter(tags=["print"])


def _fmt(dt) -> str:
    return dt.strftime("%d.%m.%Y %H:%M") if dt else "—"


async def get_default_template(db) -> dict:
    row = await db.execute(
        select(PrintTemplate).where(PrintTemplate.is_default.is_(True)).order_by(
            PrintTemplate.created_at.desc()
        )
    )
    tpl = row.scalars().first()
    return body_to_template(tpl.body) if tpl else body_to_template("")


async def build_context(db, repair: Repair) -> dict:
    city = await db.get(City, repair.city_id)
    branch = await db.get(Branch, repair.branch_id) if repair.branch_id else None
    legal_text = await get_legal_text(db)
    consent_repair_text = await get_consent_repair_text(db)
    device = " ".join(filter(None, [repair.device_type, repair.brand, repair.model]))
    complectation = (
        ", ".join(repair.complectation.get("items", []))
        if repair.complectation
        else "—"
    )
    accepted_by = repair.accepted_by_user.name if repair.accepted_by_user else "—"
    master = repair.master.name if repair.master else "в очереди"
    qr_url = f"{settings.PUBLIC_BASE_URL}/r/{repair.public_token}"

    return {
        "number": repair.number,
        "accepted_at": _fmt(repair.accepted_at),
        "city_name": city.name if city else "—",
        "branch_name": branch.name if branch else "—",
        "client_name": repair.client.full_name,
        "client_phone": repair.client.phone,
        "device": device,
        "serial": repair.serial or "—",
        "complectation": complectation,
        "fault": repair.fault_client or "—",
        "accepted_by": accepted_by,
        "master": master,
        "eta_days": str(repair.eta_days) if repair.eta_days else "",
        "legal_text": legal_text,
        "consent_repair_text": consent_repair_text,
        "consent_repair": bool(repair.consent_repair_at),
        "storage_until": _fmt(repair.storage_until),
        "qr_url": qr_url,
    }


@router.post("/repairs/{repair_id}/print")
async def create_print_job(repair_id: uuid.UUID, db: DbSession, user: CurrentUser):
    row = await db.execute(
        select(Repair)
        .where(Repair.id == repair_id)
        .options(
            selectinload(Repair.client),
            selectinload(Repair.accepted_by_user),
            selectinload(Repair.master),
        )
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")

    template = await get_default_template(db)
    ctx = await build_context(db, repair)
    currency = await get_currency(db)
    pdf = render_blank_pdf(
        template=template, currency_symbol=currency.get("symbol", "ман."), **ctx
    )

    # Конфигурация принтера попадает в payload, чтобы print-agent знал,
    # куда и как печатать (IPP напрямую или через драйвер ОС).
    printer = await get_printer(db)

    job = PrintJob(
        repair_id=repair.id,
        template_id="default",
        payload={
            "pdf_base64": base64.b64encode(pdf).decode("ascii"),
            "printer": printer,
        },
        status="queued",
        branch_id=repair.branch_id,
    )
    db.add(job)
    repair.print_count += 1
    db.add(
        RepairEvent(
            repair_id=repair.id,
            type="print",
            actor_id=user.id,
            data={"job_id": str(job.id)},
        )
    )
    await db.commit()
    await db.refresh(job)

    return {
        "job_id": job.id,
        "status": job.status,
        "pdf_base64": base64.b64encode(pdf).decode("ascii"),
    }


@router.get("/print/jobs")
async def list_print_jobs(
    db: DbSession,
    user: CurrentUser,
    status: str | None = None,
    branch_id: uuid.UUID | None = None,
):
    q = select(PrintJob).order_by(PrintJob.created_at.desc())
    if status:
        q = q.where(PrintJob.status == status)
    if branch_id:
        q = q.where(PrintJob.branch_id == branch_id)
    row = await db.execute(q.limit(50))
    return row.scalars().all()


@router.patch("/print/jobs/{job_id}")
async def update_print_job(
    job_id: uuid.UUID, db: DbSession, user: CurrentUser, body: dict
):
    job = await db.get(PrintJob, job_id)
    if job is None:
        raise HTTPException(404, "Задание печати не найдено")
    if body.get("status"):
        job.status = body["status"]
    if body.get("error"):
        job.error = body["error"]
    job.attempts += 1
    await db.commit()
    return {"ok": True, "status": job.status}
