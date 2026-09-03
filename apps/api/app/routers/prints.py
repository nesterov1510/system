"""Print jobs for A4 blanks and 58×38 repair labels.

The A4 layout is driven by the default `print_templates` row. Labels contain
client contact data and an authenticated master-card QR. The print-agent polls
`GET /print/jobs?status=queued` and routes every PDF by its payload printer
configuration (local driver, direct IPP, or remote CUPS).
"""
import base64
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.db.models import (
    Branch,
    City,
    Payment,
    PrintJob,
    PrintTemplate,
    Repair,
    RepairEvent,
    RepairMaster,
    RepairPart,
    RepairPartOrder,
    UserRole,
)
from app.services.print import (
    body_to_template,
    render_blank_pdf,
    render_repair_label_pdf,
)
from app.services.settings import (
    get_consent_repair_text,
    get_currency,
    get_label_printer,
    get_legal_text,
    get_printer,
)

router = APIRouter(tags=["print"])

PRINT_QUEUE_ROLES = {
    UserRole.ADMIN.value,
    UserRole.MANAGER.value,
    UserRole.OPERATOR.value,
}


def _can_print(user, repair: Repair) -> bool:
    """Мастер может печатать только назначенный ему ремонт."""
    if user.has_role(
        UserRole.ADMIN.value, UserRole.MANAGER.value, UserRole.OPERATOR.value
    ) or not user.has_role(UserRole.MASTER.value):
        return True
    return repair.master_id == user.id or any(
        link.user_id == user.id for link in repair.masters
    )


def _label_complectation(value: dict | None) -> str:
    """Собрать отмеченные пункты комплектации в строку для этикетки."""
    if not isinstance(value, dict):
        return ""
    items = value.get("items")
    if isinstance(items, str):
        return items.strip()
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            parts.append(text)
    return ", ".join(parts)


def _fmt(dt) -> str:
    return dt.strftime("%d.%m.%Y %H:%M") if dt else "—"


def _fmt_date(dt) -> str:
    return dt.strftime("%d.%m.%Y") if dt else ""


def _money(value, symbol: str) -> str:
    """1234.5 -> «1234.50 ман.»; пусто, если значения нет."""
    if value is None:
        return ""
    try:
        return f"{float(value):,.2f}".replace(",", " ") + f" {symbol}".rstrip()
    except (TypeError, ValueError):
        return str(value)


def _split_lines(text: str | None) -> list[str]:
    """Разбить многострочный текст на отдельные пункты (строки/«;»)."""
    if not text:
        return []
    items: list[str] = []
    for chunk in str(text).replace(";", "\n").splitlines():
        chunk = chunk.strip(" -•\t")
        if chunk:
            items.append(chunk)
    return items


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

    currency = await get_currency(db)
    symbol = currency.get("symbol", "ман.")

    # Мастера ремонта (Inžiner 1..4): сначала список, иначе основной мастер.
    master_links = [m for m in repair.masters if (m.kind or "master") != "helper"]
    helper_links = [m for m in repair.masters if (m.kind or "master") == "helper"]
    master_names = [m.user.name for m in master_links if m.user]
    if not master_names and repair.master:
        master_names = [repair.master.name]
    helper_names = [m.user.name for m in helper_links if m.user]
    # Помощники печатаются в тех же строках «Inžiner», но с пометкой
    # «(kömekçi)», чтобы отличать от основных мастеров.
    master_names_for_print = list(master_names) + [
        f"{name} (kömekçi)" for name in helper_names
    ]

    # Неисправности (Kemçilik): найденные мастером, иначе со слов клиента.
    faults = _split_lines(repair.fault_master) or _split_lines(repair.fault_client)

    # Установленные запчасти (Dakylan ätiýaçlyk şaýlary).
    rows = await db.execute(
        select(RepairPart)
        .options(selectinload(RepairPart.part))
        .where(RepairPart.repair_id == repair.id)
        .order_by(RepairPart.created_at)
    )
    parts_used = [
        f"{rp.part.name} ×{rp.qty}" if rp.qty and rp.qty > 1 else rp.part.name
        for rp in rows.scalars().all()
        if rp.part
    ]

    # Заказанные под ремонт запчасти (Sargalan ... + дата).
    rows = await db.execute(
        select(RepairPartOrder)
        .where(RepairPartOrder.repair_id == repair.id)
        .order_by(RepairPartOrder.created_at)
    )
    parts_ordered = [
        {
            "name": f"{o.name} ×{o.qty}" if o.qty and o.qty > 1 else o.name,
            "date": _fmt_date(o.ordered_at or o.created_at),
        }
        for o in rows.scalars().all()
    ]

    # Оплата: сумма проведённых платежей, иначе итоговая цена.
    rows = await db.execute(select(Payment).where(Payment.repair_id == repair.id))
    paid_total = sum(float(p.amount) for p in rows.scalars().all())
    # Поле «Tölegi» узкое — печатаем только сумму, без пометок.
    payment_text = _money(paid_total or repair.price_final, symbol)

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
        "condition": repair.condition_notes or "—",
        "accepted_by": accepted_by,
        "master": master,
        "eta_days": str(repair.eta_days) if repair.eta_days else "",
        # --- данные, которые оператор/мастер заполняет для бланка ---
        "master_names": master_names_for_print,
        "faults": faults,
        "parts_used": parts_used,
        "parts_ordered": parts_ordered,
        "work_done": repair.work_done or "",
        "warranty_text": repair.warranty_text or "",
        "repair_price": _money(repair.price_final, symbol),
        "payment_text": payment_text,
        "issued_at": _fmt(repair.issued_at) if repair.issued_at else "",
        "ready_at": _fmt(repair.ready_at) if repair.ready_at else "",
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
            selectinload(Repair.masters).selectinload(RepairMaster.user),
        )
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    if not _can_print(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")

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
    await db.flush()  # job.id нужен для события аудита до commit
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


@router.post("/repairs/{repair_id}/print-label")
async def create_label_print_job(
    repair_id: uuid.UUID, db: DbSession, user: CurrentUser
):
    """Поставить в очередь этикетку 58×38 с QR на карточку мастера."""
    row = await db.execute(
        select(Repair)
        .where(Repair.id == repair_id)
        .options(
            selectinload(Repair.client),
            selectinload(Repair.masters),
        )
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")
    if not _can_print(user, repair):
        raise HTTPException(403, "Нет доступа к этому ремонту")

    printer = await get_label_printer(db)
    if printer.get("mode") == "cups_remote" and not printer.get("ip"):
        raise HTTPException(400, "Не задан IP компьютера с принтером этикеток")
    if not printer.get("name"):
        raise HTTPException(400, "Не задано имя CUPS-очереди принтера этикеток")

    repair_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/repairs/{repair.id}"
    width_mm = printer.get("width_mm", 58)
    height_mm = printer.get("height_mm", 38)
    pdf = render_repair_label_pdf(
        repair_number=repair.number,
        client_name=repair.client.full_name,
        client_phone=repair.client.phone,
        repair_url=repair_url,
        complectation=_label_complectation(repair.complectation),
        defects=repair.condition_notes or "",
        width_mm=width_mm,
        height_mm=height_mm,
    )

    job = PrintJob(
        repair_id=repair.id,
        template_id="repair-label-58x38",
        payload={
            "document_kind": "repair_label",
            "pdf_base64": base64.b64encode(pdf).decode("ascii"),
            "printer": printer,
            "repair_url": repair_url,
        },
        status="queued",
        branch_id=repair.branch_id,
    )
    db.add(job)
    await db.flush()  # job.id нужен для события аудита до commit
    db.add(
        RepairEvent(
            repair_id=repair.id,
            type="print",
            actor_id=user.id,
            data={
                "job_id": str(job.id),
                "kind": "label",
                "printer": printer.get("name"),
            },
        )
    )
    await db.commit()
    await db.refresh(job)

    return {
        "job_id": job.id,
        "status": job.status,
        "pdf_base64": base64.b64encode(pdf).decode("ascii"),
        "repair_url": repair_url,
    }


@router.post("/repairs/{repair_id}/print-failure")
async def report_print_failure(
    repair_id: uuid.UUID, db: DbSession, user: CurrentUser, body: dict | None = None
):
    """Мастер/оператор нажал «Зарегистрировано без печати» после двух неудачных

    попыток печати. Фиксируем событие в истории ремонта и создаём уведомления
    для всех администраторов, чтобы они видели проблему с принтером.
    """
    from app.db.models import Notification, User, UserRole as _UserRole

    row = await db.execute(
        select(Repair)
        .where(Repair.id == repair_id)
        .options(selectinload(Repair.client))
    )
    repair = row.scalar_one_or_none()
    if repair is None:
        raise HTTPException(404, "Ремонт не найден")

    reason = (body or {}).get("reason") or "Печать не удалась дважды подряд"

    db.add(
        RepairEvent(
            repair_id=repair.id,
            type="print",
            actor_id=user.id,
            data={
                "kind": "print_failure",
                "message": f"Зарегистрировано без печати: {reason}",
            },
        )
    )

    admins_row = await db.execute(select(User).where(User.active.is_(True)))
    admins = [u for u in admins_row.scalars().all() if u.has_role(_UserRole.ADMIN.value)]
    for admin in admins:
        db.add(
            Notification(
                user_id=admin.id,
                type="print_failure",
                title=f"Ошибка печати · ремонт {repair.number}",
                body=(
                    f"{user.name} зарегистрировал(а) ремонт {repair.number} без "
                    f"печати бланка. Причина: {reason}"
                ),
                repair_id=repair.id,
            )
        )

    await db.commit()
    return {"ok": True, "notified_admins": len(admins)}


@router.get("/print/jobs")
async def list_print_jobs(
    db: DbSession,
    user: CurrentUser,
    status: str | None = None,
    branch_id: uuid.UUID | None = None,
):
    if not user.has_role(*PRINT_QUEUE_ROLES):
        raise HTTPException(403, "Нет доступа к очереди печати")
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
    if not user.has_role(*PRINT_QUEUE_ROLES):
        raise HTTPException(403, "Нет доступа к очереди печати")
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
