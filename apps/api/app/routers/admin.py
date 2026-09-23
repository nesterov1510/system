import base64
import json
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

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
from app.services import audit
from app.services.print import (
    AVAILABLE_FIELDS,
    DEFAULT_TEMPLATE,
    FontNotAvailable,
    body_to_template,
    normalize_template,
    render_blank_pdf,
    template_to_body,
)
from app.services.sms import (
    AVAILABLE_MASTER_FIELDS as AVAILABLE_SMS_MASTER_FIELDS,
    AVAILABLE_READY_FIELDS as AVAILABLE_SMS_READY_FIELDS,
    AVAILABLE_REMINDER_FIELDS as AVAILABLE_SMS_REMINDER_FIELDS,
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
async def create_user(payload: UserCreate, db: DbSession, actor: CurrentUser):
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email уже занят")
    extra_roles = [r for r in (payload.roles or []) if r and r != payload.role]
    from app.core.permissions import FEATURE_KEYS
    user = User(
        name=payload.name,
        email=payload.email.lower(),
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=payload.role,
        extra_roles=extra_roles or None,
        extra_permissions=[k for k in (payload.permissions or []) if k in FEATURE_KEYS] or None,
        city_id=payload.city_id,
        branch_id=payload.branch_id,
        active=payload.active,
    )
    db.add(user)
    await db.flush()  # нужен user.id для журнала аудита
    await audit.record(
        db,
        audit.ACTION_USER_CREATE,
        actor_id=actor.id,
        entity="user",
        entity_id=user.id,
        meta={"email": user.email, "role": user.role, "roles": user.roles},
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, payload: UserUpdate, db: DbSession, actor: CurrentUser
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    roles = data.pop("roles", None)
    permissions = data.pop("permissions", None)
    if "email" in data:
        new_email = (data["email"] or "").strip().lower()
        if not new_email:
            raise HTTPException(400, "Email не может быть пустым")
        clash = await db.execute(
            select(User).where(User.email == new_email, User.id != user_id)
        )
        if clash.scalar_one_or_none():
            raise HTTPException(409, "Email уже занят")
        data["email"] = new_email
    for field, value in data.items():
        setattr(user, field, value)
    if roles is not None:
        base_role = data.get("role", user.role)
        user.extra_roles = [r for r in roles if r and r != base_role] or None
    if permissions is not None:
        from app.core.permissions import FEATURE_KEYS
        user.extra_permissions = [k for k in permissions if k in FEATURE_KEYS] or None
    if password:
        user.password_hash = hash_password(password)
    await audit.record(
        db,
        audit.ACTION_USER_UPDATE,
        actor_id=actor.id,
        entity="user",
        entity_id=user_id,
        meta={
            "fields": sorted(data.keys()),
            "password_changed": bool(password),
            "roles_changed": roles is not None,
            "permissions_changed": permissions is not None,
            "role": user.role,
            "roles": user.roles,
        },
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}")
async def deactivate_user(user_id: uuid.UUID, db: DbSession, user: CurrentUser):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Пользователь не найден")
    if target.id == user.id:
        raise HTTPException(400, "Нельзя отключить самого себя")
    target.active = False
    await audit.record(
        db,
        audit.ACTION_USER_DEACTIVATE,
        actor_id=user.id,
        entity="user",
        entity_id=user_id,
        meta={"email": target.email, "role": target.role},
    )
    await db.commit()
    return {"ok": True}


# --- Settings ---
@router.get("/settings", response_model=list[SettingOut])
async def list_settings(db: DbSession):
    row = await db.execute(select(Setting).order_by(Setting.key))
    return row.scalars().all()


@router.put("/settings/{key}", response_model=SettingOut)
async def upsert_setting(key: str, payload: SettingIn, db: DbSession, actor: CurrentUser):
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None:
        setting = Setting(key=key, value=payload.value, description=payload.description)
        db.add(setting)
    else:
        setting.value = payload.value
        setting.description = payload.description
    # В настройках могут лежать секреты (пароль SMS-шлюза) — в аудит пишем
    # только имя ключа, без значений.
    await audit.record(
        db,
        audit.ACTION_SETTING_UPDATE,
        actor_id=actor.id,
        entity="setting",
        entity_id=key,
        meta={"key": key, "sensitive": key in ("sms_server",)},
    )
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
    """Настроить принтер бланков A4 (очередь CUPS на сервере MSB)."""
    from app.services.settings import PRINTER_MODES, set_setting

    try:
        port = int(body.get("port", 631))
    except (TypeError, ValueError):
        raise HTTPException(400, "Порт должен быть числом")
    if not 1 <= port <= 65535:
        raise HTTPException(400, "Некорректный порт")

    mode = str(body.get("mode", "cups_local")).strip()
    if mode not in PRINTER_MODES:
        raise HTTPException(400, f"Режим должен быть одним из: {', '.join(PRINTER_MODES)}")

    value = {
        "ip": str(body.get("ip", "")).strip(),
        "port": port,
        "mode": mode,
        "name": str(body.get("name", "")).strip(),
    }
    if not value["name"]:
        raise HTTPException(400, "Укажите имя очереди принтера")
    # Локальной очереди адрес знает сам CUPS (`lpstat -v office_printer_a4`),
    # поэтому IP нужен только удалённому CUPS и прямой печати по IPP.
    if mode in ("cups_remote", "ipp") and not value["ip"]:
        raise HTTPException(400, "Укажите IP компьютера с принтером")

    await set_setting(
        db,
        "printer",
        value,
        "Принтер бланков A4: очередь CUPS, режим печати",
    )
    return {"printer": value}


@router.put("/printer/label")
async def set_label_printer_config(db: DbSession, body: dict):
    """Настроить CUPS-очередь для этикеток ремонта."""
    from app.services.settings import LABEL_PRINTER_MODES, set_setting

    mode = str(body.get("mode", "raw_tspl")).strip()
    if mode not in LABEL_PRINTER_MODES:
        raise HTTPException(400, f"Режим должен быть одним из: {', '.join(LABEL_PRINTER_MODES)}")

    default_port = 9100 if mode == "raw_tspl" else 631
    try:
        port = int(body.get("port", default_port))
    except (TypeError, ValueError):
        raise HTTPException(400, "Порт должен быть числом")
    if not 1 <= port <= 65535:
        raise HTTPException(400, "Некорректный порт")

    value = {
        "ip": str(body.get("ip", "")).strip(),
        "port": port,
        "mode": mode,
        "name": str(body.get("name", "")).strip(),
        "width_mm": 58,
        "height_mm": 38,
        "gap_mm": _clamp_gap(body.get("gap_mm")),
        "media": str(body.get("media", "")).strip(),
    }
    if mode == "raw_tspl":
        # Принтер не в CUPS: ему нужен адрес и raw-порт 9100, имя не важно.
        if not value["ip"]:
            raise HTTPException(400, "Укажите адрес принтера этикеток")
    else:
        # CUPS-режимам нужна очередь; удалённому CUPS — ещё и адрес.
        if not value["name"]:
            raise HTTPException(400, "Укажите имя очереди принтера")
        if mode == "cups_remote" and not value["ip"]:
            raise HTTPException(400, "Укажите IP компьютера с CUPS")

    await set_setting(
        db,
        "label_printer",
        value,
        "Принтер этикеток 58×38 мм (raw TSPL или CUPS)",
    )
    return {"label_printer": value}


def _clamp_gap(value, default: float = 2.0) -> float:
    try:
        return min(10.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


@router.post("/printer/test")
async def test_print(db: DbSession):
    """Создаёт тестовое задание печати (маленький PDF), чтобы проверить принтер."""
    from app.services.settings import get_printer

    printer = await get_printer(db)
    try:
        pdf = _render_test_pdf()
    except FontNotAvailable as exc:
        # Не 500: админ должен увидеть, что нужно установить шрифты.
        raise HTTPException(503, str(exc))
    return await _queue_test_print(db, pdf, printer, template_id="test")


def _render_test_pdf() -> bytes:
    """Тестовый бланк без реальных данных (проверка принтера и шрифтов)."""
    return render_blank_pdf(
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


async def _queue_test_print(db, pdf: bytes, printer: dict, *, template_id: str) -> dict:
    """Положить готовый PDF в очередь печати."""
    job = PrintJob(
        repair_id=None,
        template_id=template_id,
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

    from app.services.print import render_repair_label_pdf, render_repair_label_tspl
    from app.services.settings import get_label_printer

    printer = await get_label_printer(db)
    if printer.get("mode") == "raw_tspl":
        if not str(printer.get("ip") or "").strip():
            raise HTTPException(400, "Не задан адрес принтера этикеток (TSPL)")
    else:
        if not printer.get("name"):
            raise HTTPException(400, "Не настроен CUPS-принтер этикеток (имя очереди)")
        if printer.get("mode") == "cups_remote" and not printer.get("ip"):
            raise HTTPException(400, "Не задан IP компьютера с CUPS-принтером этикеток")

    from app.services.public_url import public_base_url

    repair_url = f"{public_base_url()}/repairs"
    common = dict(
        repair_number="ТЕСТ-58x38",
        client_name="Тестовый клиент",
        client_phone="+993 61 000000",
        complectation="Пульт, Шнур питания",
        defects="Царапины, Линии на экране",
        width_mm=printer.get("width_mm", 58),
        height_mm=printer.get("height_mm", 38),
    )
    is_tspl = printer.get("mode") == "raw_tspl"
    try:
        if is_tspl:
            data = render_repair_label_tspl(
                **common, repair_url=repair_url, gap_mm=printer.get("gap_mm", 2)
            )
        else:
            data = render_repair_label_pdf(**common, repair_url=repair_url)
    except FontNotAvailable as exc:
        raise HTTPException(503, str(exc))
    document_key = "raw_base64" if is_tspl else "pdf_base64"
    job = PrintJob(
        repair_id=None,
        template_id="label-test",
        payload={
            "document_kind": "repair_label",
            "document_format": "tspl" if is_tspl else "pdf",
            document_key: base64.b64encode(data).decode("ascii"),
            "printer": printer,
            "repair_url": repair_url,
        },
        status="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"job_id": job.id, "status": job.status, "repair_url": repair_url}


# --- SMS gateway settings ---
@router.get("/sms")
async def get_sms_config(db: DbSession):
    """Настройки SMS-шлюза + текущие тексты шаблонов (для формы в админке)."""
    from app.services.settings import get_sms_server, get_sms_templates

    server = await get_sms_server(db)
    server = dict(server)
    server["password"] = "•" * 8 if server.get("password") else ""
    templates = await get_sms_templates(db)
    return {
        "server": server,
        "templates": templates,
        "template_fields": {
            "master_assign": AVAILABLE_SMS_MASTER_FIELDS,
            "ready": AVAILABLE_SMS_READY_FIELDS,
            "pickup_reminder": AVAILABLE_SMS_REMINDER_FIELDS,
        },
    }


@router.put("/sms")
async def set_sms_config(db: DbSession, body: dict):
    """Сохранить настройки SMS-шлюза (URL, логин/пароль, вкл/выкл)."""
    from app.services.settings import get_sms_server, set_setting

    current = await get_sms_server(db)
    password = body.get("password")
    # Пустая/маскированная строка пароля из формы — не затираем сохранённый.
    if password is None or (isinstance(password, str) and password.strip("•") == ""):
        password = current.get("password", "")

    try:
        timeout_sec = float(body.get("timeout_sec", current.get("timeout_sec", 10.0)))
    except (TypeError, ValueError):
        raise HTTPException(400, "Таймаут должен быть числом")

    value = {
        "enabled": bool(body.get("enabled", current.get("enabled", False))),
        "url": str(body.get("url", current.get("url", ""))).strip(),
        "username": str(body.get("username", current.get("username", ""))).strip(),
        "password": password,
        "verify_ssl": bool(body.get("verify_ssl", current.get("verify_ssl", False))),
        "timeout_sec": timeout_sec,
    }
    if value["enabled"] and not value["url"]:
        raise HTTPException(400, "Укажите адрес SMS-шлюза")

    await set_setting(db, "sms_server", value, "SMS-шлюз: адрес, логин/пароль, таймаут")
    out = dict(value)
    out["password"] = "•" * 8 if out.get("password") else ""
    return {"server": out}


@router.put("/sms/templates")
async def set_sms_templates(db: DbSession, body: dict):
    """Сохранить редактируемые шаблоны текстов SMS (мастеру / клиенту)."""
    from app.services.settings import get_sms_templates, set_setting

    current = await get_sms_templates(db)
    value = {
        "master_assign": str(
            body.get("master_assign", current.get("master_assign", ""))
        ).strip(),
        "ready": str(body.get("ready", current.get("ready", ""))).strip(),
        # Ежедневное напоминание «заберите технику». Пустая строка = текст по
        # умолчанию (название сервиса + адрес), см. services/sms.py.
        "pickup_reminder": str(
            body.get("pickup_reminder", current.get("pickup_reminder", ""))
        ).strip(),
    }
    await set_setting(db, "sms_templates", value, "Шаблоны текстов SMS")
    return {"templates": value}


@router.post("/sms/test")
async def test_sms(db: DbSession, body: dict):
    """Отправить тестовое SMS на указанный номер — проверка шлюза из админки."""
    from app.services.sms import send_sms

    phone = str(body.get("phone", "")).strip()
    if not phone:
        raise HTTPException(400, "Укажите номер телефона для теста")
    text = str(body.get("text") or "Тестовое сообщение MSB: шлюз SMS настроен верно.")
    result = await send_sms(phone, text, db=db)
    if not result.get("ok"):
        raise HTTPException(
            502, f"Не удалось отправить тестовое SMS: {result.get('detail', 'ошибка шлюза')}"
        )
    return {"ok": True, "detail": result.get("detail")}


# --- Ежедневные напоминания «заберите технику» ---
@router.get("/reminders")
async def reminders_queue(db: DbSession):
    """Очередь напоминаний: какие ремонты и когда получат следующее SMS.

    Нужно администратору, чтобы проверить, что рассылка жива: после «Ремонт
    закончен» ремонт должен появиться здесь с датой следующего напоминания.
    """
    from app.services.reminders import (
        REMINDER_STATUSES,
        days_waiting,
        in_sending_window,
        local_now,
    )

    rows = await db.execute(
        select(Repair)
        .options(selectinload(Repair.client))
        .where(Repair.reminder_next_at.isnot(None))
        .order_by(Repair.reminder_next_at)
        .limit(200)
    )
    repairs = rows.scalars().all()
    return {
        "enabled": settings.REMINDER_ENABLED,
        "sms_window_open": in_sending_window(),
        "local_time": local_now().isoformat(),
        "schedule": {
            "every_hours": settings.REMINDER_EVERY_HOURS,
            "first_delay_hours": settings.REMINDER_FIRST_DELAY_HOURS,
            "check_interval_min": settings.REMINDER_CHECK_INTERVAL_MIN,
            "quiet_hours": f"{settings.REMINDER_SEND_FROM_HOUR}:00–"
            f"{settings.REMINDER_SEND_TO_HOUR}:00 {settings.REMINDER_TIMEZONE}",
            "max_count": settings.REMINDER_MAX_COUNT,
            "statuses": list(REMINDER_STATUSES),
        },
        "items": [
            {
                "id": str(r.id),
                "number": r.number,
                "status": r.status,
                "client_name": r.client.full_name if r.client else None,
                "client_phone": r.client.phone if r.client else None,
                "ready_at": r.ready_at.isoformat() if r.ready_at else None,
                "days_waiting": days_waiting(r),
                "sent_count": r.reminder_count or 0,
                "last_sent_at": (
                    r.reminder_last_at.isoformat() if r.reminder_last_at else None
                ),
                "next_at": r.reminder_next_at.isoformat() if r.reminder_next_at else None,
            }
            for r in repairs
        ],
    }


@router.post("/reminders/run")
async def run_reminders_now(db: DbSession, user: CurrentUser):
    """Прогнать очередь напоминаний вручную (проверка шлюза и расписания).

    Отправляет только те напоминания, срок которых уже подошёл, — так же, как
    фоновая задача. Двойной запуск не приведёт к дублю SMS: строка ремонта
    «заявляется» условным UPDATE.
    """
    from app.services import audit as audit_service
    from app.services.reminders import send_due_reminders

    report = await send_due_reminders(db)
    await audit_service.record(
        db,
        "reminders.run",
        actor_id=user.id,
        entity="system",
        meta={k: report.get(k) for k in ("sent", "failed", "skipped", "due", "reason")},
    )
    await db.commit()
    return report


# --- Резервная копия: экспорт / импорт данных ---
MAX_IMPORT_BYTES = 512 * 1024 * 1024


@router.get("/backup/export")
async def backup_export(
    db: DbSession,
    user: CurrentUser,
    media: bool = False,
    format: str = "zip",
):
    """Выгрузить все данные архивом `msb_backup.zip` (meta.json + msb_export.json).

    `media=1` — добавить в архив файлы фотографий (папка media/).
    `format=json` — отдать только msb_export.json без архива.
    """
    from fastapi.responses import Response

    from app.services import backup

    if format == "json":
        payload = await backup.build_export(db, exported_by=user.email)
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        filename = backup.backup_filename(payload["exported_at"]).replace(".zip", ".json")
        media_type = "application/json"
    else:
        body, meta = await backup.build_backup_zip(
            db, exported_by=user.email, include_media=bool(media)
        )
        filename = backup.backup_filename(meta["exported_at"])
        media_type = "application/zip"
    await audit.record(
        db,
        audit.ACTION_DATA_EXPORT,
        actor_id=user.id,
        entity="system",
        meta={"filename": filename, "media": bool(media), "bytes": len(body)},
    )
    await db.commit()
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backup/preview")
async def backup_preview(db: DbSession):
    """Сколько записей уйдёт в выгрузку (для страницы админки)."""
    from app.services import backup

    tables = await backup.export_tables(db)
    counts = {k: len(v) for k, v in tables.items()}
    return {"tables": counts, "total": sum(counts.values())}


@router.post("/backup/import")
async def backup_import(
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    mode: str = Form("merge"),
    dry_run: bool = Form(False),
):
    """Загрузить `msb_backup.zip` (или msb_export.json).

    `mode=merge` — добавить и обновить записи, `mode=replace` — сначала
    очистить клиентов, ремонты и склад разбора. `dry_run=1` — только
    проверить файл и показать, что в нём, ничего не записывая.
    """
    from app.services import backup

    data = await file.read()
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "Файл слишком большой")
    try:
        payload, meta, media_files = backup.read_backup_file(data, file.filename or "")
    except backup.ImportError_ as e:
        raise HTTPException(400, str(e))
    tables = payload.get("tables") or {}
    summary = {
        k: len(v) for k, v in tables.items() if isinstance(v, list)
    }
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "meta": meta,
            "version": payload.get("version"),
            "exported_at": payload.get("exported_at"),
            "tables": summary,
            "media_files": len(media_files),
        }
    report = await backup.import_payload(
        db, payload, actor=user, mode=mode, media=media_files, source_meta=meta
    )
    result = report.as_dict()
    result["filename"] = file.filename
    await audit.record(
        db,
        audit.ACTION_DATA_IMPORT,
        actor_id=user.id,
        entity="system",
        meta={
            "filename": file.filename,
            "mode": report.mode,
            "ok": report.error is None,
            "error": report.error,
            "created": report.created,
            "updated": report.updated,
            "skipped": report.skipped,
        },
    )
    await db.commit()
    if report.error:
        raise HTTPException(400, result)
    return result


# --- Audit log ---
@router.get("/audit")
async def list_audit(
    db: DbSession,
    action: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
):
    """Журнал значимых действий (касса, финансы, удаления, назначения).

    `repair_events` для этого не подходит: он удаляется вместе с ремонтом.
    """
    from app.db.models import AuditLog

    limit = max(1, min(int(limit or 100), 500))
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id:
        q = q.where(AuditLog.entity_id == str(entity_id))
    rows = (await db.execute(q)).scalars().all()

    # Кто совершил действие — одним запросом, без N+1.
    actor_ids = {r.actor_id for r in rows if r.actor_id}
    names: dict = {}
    if actor_ids:
        users = await db.execute(select(User).where(User.id.in_(actor_ids)))
        names = {u.id: u.name for u in users.scalars().all()}

    return [
        {
            "id": r.id,
            "created_at": r.created_at,
            "action": r.action,
            "entity": r.entity,
            "entity_id": r.entity_id,
            "actor_id": r.actor_id,
            "actor_name": names.get(r.actor_id),
            "meta": r.meta,
            "ip": r.ip,
        }
        for r in rows
    ]


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
async def preview_print_template(db: DbSession, body: dict, request: Request):
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

    from app.services.public_url import public_status_url

    if repair:
        from app.routers.prints import build_context

        ctx = await build_context(db, repair, request)
    else:
        # Пример для превью — из региона развёртывания (Ашхабад, +993, ман.),
        # а не из старой «московской» версии системы.
        ctx = {
            "number": "TV-ASG-2026-00000",
            "accepted_at": "26.08.2026 14:02",
            "city_name": "Ашхабад",
            "branch_name": "Центральная точка",
            "client_name": "Мерданов Мердан",
            "client_phone": "+993 61 000000",
            "device": "Телевизор Samsung UE55",
            "serial": "SN123456",
            "complectation": "ПДУ, Кабель питания",
            "fault": "не включается",
            "accepted_by": "Оператор Анна",
            "master": "Мастер Сердар",
            "eta_days": "6",
            "legal_text": "Техника хранится в сервисном центре бесплатно в течение 3 (трёх) месяцев с момента уведомления о готовности.",
            "storage_until": "26.11.2026 14:02",
            "qr_url": public_status_url("example-token"),
        }

    try:
        pdf = render_blank_pdf(template=template, **ctx)
    except FontNotAvailable as exc:
        raise HTTPException(503, str(exc))
    return PDFResponse(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=preview.pdf"},
    )
