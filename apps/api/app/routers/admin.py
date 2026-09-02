import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import AdminOnly, CurrentUser, DbSession
from app.core.security import hash_password
from app.db.models import (
    Branch,
    City,
    PrintJob,
    PrintTemplate,
    Repair,
    RepairMaster,
    Setting,
    User,
)
from app.schemas.admin import (
    BranchCreate,
    BranchOut,
    CityCreate,
    CityOut,
    SettingIn,
    SettingOut,
)
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.print import (
    AVAILABLE_FIELDS,
    DEFAULT_TEMPLATE,
    body_to_template,
    normalize_template,
    render_blank_pdf,
    template_to_body,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[AdminOnly])


# --- Cities ---
@router.get("/cities", response_model=list[CityOut])
async def list_cities(db: DbSession):
    row = await db.execute(select(City).order_by(City.name))
    return row.scalars().all()


@router.post("/cities", response_model=CityOut, status_code=201)
async def create_city(payload: CityCreate, db: DbSession):
    city = City(slug=payload.slug.lower(), name=payload.name, timezone=payload.timezone)
    db.add(city)
    await db.commit()
    await db.refresh(city)
    return city


@router.patch("/cities/{city_id}", response_model=CityOut)
async def update_city(city_id: uuid.UUID, payload: CityCreate, db: DbSession):
    city = await db.get(City, city_id)
    if city is None:
        raise HTTPException(404, "Город не найден")
    city.slug = payload.slug.lower()
    city.name = payload.name
    city.timezone = payload.timezone
    await db.commit()
    return city


# --- Branches ---
@router.get("/branches", response_model=list[BranchOut])
async def list_branches(db: DbSession):
    row = await db.execute(select(Branch).order_by(Branch.name))
    return row.scalars().all()


@router.post("/branches", response_model=BranchOut, status_code=201)
async def create_branch(payload: BranchCreate, db: DbSession):
    branch = Branch(**payload.model_dump())
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.patch("/branches/{branch_id}", response_model=BranchOut)
async def update_branch(branch_id: uuid.UUID, payload: BranchCreate, db: DbSession):
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404, "Точка не найдена")
    for field, value in payload.model_dump().items():
        setattr(branch, field, value)
    await db.commit()
    return branch


# --- Users ---
@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbSession):
    row = await db.execute(select(User).order_by(User.name))
    return row.scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, db: DbSession):
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email уже занят")
    user = User(
        name=payload.name,
        email=payload.email.lower(),
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=payload.role,
        city_id=payload.city_id,
        branch_id=payload.branch_id,
        active=payload.active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, payload: UserUpdate, db: DbSession):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for field, value in data.items():
        setattr(user, field, value)
    if password:
        user.password_hash = hash_password(password)
    await db.commit()
    return user


@router.delete("/users/{user_id}")
async def deactivate_user(user_id: uuid.UUID, db: DbSession, user: CurrentUser):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Пользователь не найден")
    if target.id == user.id:
        raise HTTPException(400, "Нельзя отключить самого себя")
    target.active = False
    await db.commit()
    return {"ok": True}


# --- Settings ---
@router.get("/settings", response_model=list[SettingOut])
async def list_settings(db: DbSession):
    row = await db.execute(select(Setting).order_by(Setting.key))
    return row.scalars().all()


@router.put("/settings/{key}", response_model=SettingOut)
async def upsert_setting(key: str, payload: SettingIn, db: DbSession):
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None:
        setting = Setting(key=key, value=payload.value, description=payload.description)
        db.add(setting)
    else:
        setting.value = payload.value
        setting.description = payload.description
    await db.commit()
    return setting


# --- Printer settings ---
@router.get("/printer")
async def get_printer_config(db: DbSession):
    from app.services.settings import get_label_printer, get_printer

    printer = await get_printer(db)
    label_printer = await get_label_printer(db)
    row = await db.execute(
        select(PrintJob).order_by(PrintJob.created_at.desc()).limit(10)
    )
    jobs = [
        {
            "id": j.id,
            "status": j.status,
            "error": j.error,
            "created_at": j.created_at,
            "template_id": j.template_id,
            "printer_name": ((j.payload or {}).get("printer") or {}).get("name"),
        }
        for j in row.scalars().all()
    ]
    return {
        "printer": printer,
        "label_printer": label_printer,
        "recent_jobs": jobs,
    }


@router.put("/printer")
async def set_printer_config(db: DbSession, body: dict):
    from app.services.settings import set_setting

    value = {
        "ip": body.get("ip", ""),
        "port": int(body.get("port", 631)),
        "mode": body.get("mode", "agent"),  # agent | ipp
        "name": body.get("name", "Epson L3250"),
    }
    await set_setting(db, "printer", value, "Принтер: IP, порт, режим печати (agent|ipp)")
    return {"printer": value}


@router.put("/printer/label")
async def set_label_printer_config(db: DbSession, body: dict):
    """Настроить CUPS-очередь для этикеток ремонта."""
    from app.services.settings import set_setting

    try:
        port = int(body.get("port", 631))
    except (TypeError, ValueError):
        raise HTTPException(400, "Порт CUPS должен быть числом")

    if not 1 <= port <= 65535:
        raise HTTPException(400, "Некорректный порт CUPS")

    value = {
        "ip": str(body.get("ip", "")).strip(),
        "port": port,
        "mode": "cups_remote",
        "name": str(body.get("name", "3B-350B")).strip(),
        "width_mm": 58,
        "height_mm": 38,
        "media": str(body.get("media", "")).strip(),
    }
    if not value["name"]:
        raise HTTPException(400, "Укажите имя очереди принтера")
    if not value["ip"]:
        raise HTTPException(400, "Укажите IP компьютера с CUPS")

    await set_setting(
        db,
        "label_printer",
        value,
        "CUPS-принтер этикеток ремонта",
    )
    return {"label_printer": value}


@router.post("/printer/test")
async def test_print(db: DbSession):
    """Создаёт тестовое задание печати (маленький PDF), чтобы проверить принтер."""
    import base64

    from app.services.print import render_blank_pdf
    from app.services.settings import get_printer

    printer = await get_printer(db)
    pdf = render_blank_pdf(
        template={"copies": 1, "signature": False},
        number="ТЕСТ-ПЕЧАТЬ",
        accepted_at="—",
        city_name="—",
        branch_name="—",
        client_name="Тестовая печать",
        client_phone="—",
        device="Проверка принтера",
        serial="—",
        complectation="—",
        fault="—",
        accepted_by="—",
        master="—",
        eta_days="",
        legal_text="",
        storage_until="—",
        qr_url="",
    )
    job = PrintJob(
        repair_id=None,
        template_id="test",
        payload={
            "pdf_base64": base64.b64encode(pdf).decode("ascii"),
            "printer": printer,
        },
        status="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"job_id": job.id, "status": job.status}


@router.post("/printer/label/test")
async def test_label_print(db: DbSession):
    """Поставить в очередь тестовую этикетку заданного физического размера."""
    import base64

    from app.services.print import render_repair_label_pdf
    from app.services.settings import get_label_printer

    printer = await get_label_printer(db)
    if not printer.get("name") or not printer.get("ip"):
        raise HTTPException(400, "Не настроен удалённый CUPS-принтер этикеток")

    repair_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/repairs"
    pdf = render_repair_label_pdf(
        repair_number="ТЕСТ-58x38",
        client_name="Тестовый клиент",
        client_phone="+993 61 000000",
        repair_url=repair_url,
        width_mm=printer.get("width_mm", 58),
        height_mm=printer.get("height_mm", 38),
    )
    job = PrintJob(
        repair_id=None,
        template_id="label-test",
        payload={
            "document_kind": "repair_label",
            "pdf_base64": base64.b64encode(pdf).decode("ascii"),
            "printer": printer,
            "repair_url": repair_url,
        },
        status="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"job_id": job.id, "status": job.status}


# --- Print templates (бланк) ---
@router.get("/print-templates")
async def list_print_templates(db: DbSession):
    row = await db.execute(select(PrintTemplate).order_by(PrintTemplate.created_at))
    out = []
    for t in row.scalars().all():
        out.append(
            {
                "id": t.id,
                "name": t.name,
                "is_default": t.is_default,
                "body": body_to_template(t.body),
            }
        )
    return out


@router.get("/print-templates/meta")
async def print_template_meta():
    return {"fields": AVAILABLE_FIELDS, "default": DEFAULT_TEMPLATE}


@router.post("/print-templates")
async def create_print_template(db: DbSession, body: dict):
    template = normalize_template(body.get("body") or {})
    if body.get("is_default"):
        await _unset_defaults(db)
    tpl = PrintTemplate(
        name=body.get("name") or template["name"],
        body=template_to_body(template),
        is_default=bool(body.get("is_default")),
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return {"id": tpl.id, "name": tpl.name, "is_default": tpl.is_default, "body": template}


@router.patch("/print-templates/{template_id}")
async def update_print_template(template_id: uuid.UUID, db: DbSession, body: dict):
    tpl = await db.get(PrintTemplate, template_id)
    if tpl is None:
        raise HTTPException(404, "Шаблон не найден")
    if "name" in body:
        tpl.name = body["name"]
    if "body" in body:
        tpl.body = template_to_body(normalize_template(body["body"]))
    if body.get("is_default"):
        await _unset_defaults(db)
        tpl.is_default = True
    await db.commit()
    await db.refresh(tpl)
    return {
        "id": tpl.id,
        "name": tpl.name,
        "is_default": tpl.is_default,
        "body": body_to_template(tpl.body),
    }


async def _unset_defaults(db):
    row = await db.execute(
        select(PrintTemplate).where(PrintTemplate.is_default.is_(True))
    )
    for t in row.scalars().all():
        t.is_default = False


@router.post("/print-templates/preview")
async def preview_print_template(db: DbSession, body: dict):
    """Render a preview PDF from a template (and optional real repair)."""
    from fastapi.responses import Response as PDFResponse

    template = normalize_template(body.get("body") or {})

    repair = None
    if body.get("repair_id"):
        from sqlalchemy.orm import selectinload

        row = await db.execute(
            select(Repair)
            .where(Repair.id == uuid.UUID(body["repair_id"]))
            .options(
                selectinload(Repair.client),
                selectinload(Repair.accepted_by_user),
                selectinload(Repair.master),
                selectinload(Repair.masters).selectinload(RepairMaster.user),
            )
        )
        repair = row.scalar_one_or_none()

    if repair:
        from app.routers.prints import build_context

        ctx = await build_context(db, repair)
    else:
        ctx = {
            "number": "TV-MSK-2026-00000",
            "accepted_at": "26.08.2026 14:02",
            "city_name": "Москва",
            "branch_name": "Центральная точка",
            "client_name": "Иванов Иван Иванович",
            "client_phone": "+7 900 000-00-00",
            "device": "ТВ Samsung UE55",
            "serial": "SN123456",
            "complectation": "ПДУ, Кабель питания",
            "fault": "не включается",
            "accepted_by": "Оператор Анна",
            "master": "Мастер Сергей",
            "eta_days": "6",
            "legal_text": "Техника хранится в сервисном центре бесплатно в течение 3 (трёх) месяцев с момента уведомления о готовности.",
            "storage_until": "26.11.2026 14:02",
            "qr_url": f"{settings.PUBLIC_BASE_URL}/r/example-token",
        }

    pdf = render_blank_pdf(template=template, **ctx)
    return PDFResponse(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=preview.pdf"},
    )
