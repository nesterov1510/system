"""Разбор формы приёмки — общий для внутренней и публичной страницы.

Обе страницы (`/repairs/new` для сотрудников и `/intake` без аккаунта)
отправляют один и тот же набор полей. Правила разбора живут здесь, чтобы
публичная приёмка не «съехала» со временем относительно обычной.
"""
import re
import uuid

from app.schemas.repair import ClientCreate, RepairCreate
from app.services.numbering import (
    DEFAULT_COUNTRY_CODE,
    phone_digits,
    validate_tm_phone,
)
from app.webui.catalog import normalize_class

# Комплектация по форме эталона: чекбоксы equipment[] + «другое».
EQUIP_LABELS = {
    "remote": "Пульт", "power_cable": "Шнур питания", "legs": "Ножки",
    "wall_mount": "Настенное крепление", "box_ir_eye": "Глазок/ИК-приёмник",
    "box": "Коробка", "all_in_box": "Всё в комплекте в коробке",
}

# Внешнее состояние: предустановленные отметки + свободный текст.
COND_LABELS = {
    "screen_scratches": "Царапины на экране",
    "body_scratches": "Царапины на корпусе",
    "broken_parts": "Есть сломанные места",
    "other_service": "Был в другом сервисе",
}


def caps_ident(value: str | None) -> str | None:
    """Марка / модель / SN в приёмке всегда заглавными."""
    text = (value or "").strip()
    return text.upper() or None


def parse_identity(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """Разбор строки «МАРКА-МОДЕЛЬ-SN», как в televisions.js."""
    value = (raw or "").strip().upper()
    if not value:
        return None, None, None
    spaced = [part.strip() for part in re.split(r"\s+[-–—]\s+", value) if part.strip()]
    if len(spaced) >= 3:
        return spaced[0], spaced[1], " - ".join(spaced[2:]) or None
    compact = value.split("-")
    if len(compact) >= 3:
        return (
            compact[0].strip() or None,
            compact[1].strip() or None,
            "-".join(compact[2:]).strip() or None,
        )
    if len(compact) == 2:
        return compact[0].strip() or None, compact[1].strip() or None, None
    return value, None, None


async def iter_comp(form):
    """Кастомные позиции комплектации из справочника (поля comp_*)."""
    for key in form:
        if key.startswith("comp_"):
            yield key[5:]


def parse_complectation(form) -> dict:
    """Комплектация: чекбоксы справочника + эталонные + «другое» через запятую."""
    comp: dict = {}
    for key in form:
        if key.startswith("comp_"):
            comp[key[5:]] = True
    for val in form.getlist("equipment"):
        comp[EQUIP_LABELS.get(val, val)] = True
    equip_other = (form.get("equipment_other") or "").strip()
    if equip_other:
        for item in equip_other.split(","):
            item = item.strip()
            if item:
                comp[item] = True
    custom = (form.get("complectation_custom") or "").strip()
    if custom:
        for item in custom.split(","):
            item = item.strip()
            if item:
                comp[item] = True
    return comp


def parse_condition(form) -> str | None:
    """Внешнее состояние: отметки + свободный текст, через «;»."""
    parts = [COND_LABELS[v] for v in form.getlist("condition") if v in COND_LABELS]
    other = (form.get("condition_other") or "").strip()
    if other:
        parts.append(other)
    return "; ".join(parts) or None


def validate_phones(form) -> str | None:
    """Телефон заказчика и дополнительного контакта. Вернуть текст ошибки."""
    # Номер телефона: +993 + код оператора (12, 60–65, 71, 72) + 6 цифр.
    # На форме это проверяет priemka/phone.js, но форму можно отправить и
    # в обход скрипта — поэтому проверка повторяется здесь.
    phone_err = validate_tm_phone(form.get("phone", ""))
    if phone_err:
        return f"Номер телефона заказчика: {phone_err}"
    contact2_raw = (form.get("contact2_phone") or "").strip()
    if phone_digits(contact2_raw) not in ("", DEFAULT_COUNTRY_CODE):
        contact2_err = validate_tm_phone(contact2_raw)
        if contact2_err:
            return f"Телефон дополнительного контакта: {contact2_err}"
    return None


def parse_intake_form(form, *, master_id: uuid.UUID | None = None) -> RepairCreate:
    """Собрать RepairCreate из данных формы приёмки.

    Ошибки телефона проверяются отдельно (`validate_phones`), чтобы вызывающий
    код мог показать их на своей форме. `master_id` передаёт только внутренняя
    страница: на публичной мастера не назначают — ремонт уходит в очередь.
    """
    comp = parse_complectation(form)
    condition_notes = parse_condition(form)

    # Кнопка «Доставка» присылает "1"/"0"; bool("0") дал бы True, и каждый
    # заказ считался бы привезённым с доставкой.
    is_delivery = (form.get("is_delivery") or "").strip() in ("1", "true", "on")
    delivery_district = (form.get("delivery_district") or "").strip() or None
    delivery_comment = (form.get("delivery_comment") or "").strip() or None
    if not is_delivery:
        delivery_district = None
        delivery_comment = None

    brand = caps_ident(form.get("brand_manual") or form.get("brand"))
    model = caps_ident(form.get("model_manual") or form.get("model"))
    serial = caps_ident(form.get("serial_manual") or form.get("serial"))
    if not brand and not model and not serial:
        brand, model, serial = parse_identity(form.get("identity_raw"))

    return RepairCreate(
        city_id=uuid.UUID(form["city_id"]),
        client=ClientCreate(
            full_name=form.get("full_name", ""),
            phone=form.get("phone", ""),
            consent_pdn=bool(form.get("consent_pdn")),
            consent_storage=bool(form.get("consent_storage")),
        ),
        contact2_name=(form.get("contact2_name") or "").strip() or None,
        contact2_phone=(form.get("contact2_phone") or "").strip() or None,
        contact2_relation=(form.get("contact2_relation") or "").strip() or None,
        device_type=normalize_class(form.get("device_type") or "Другое"),
        brand=brand,
        model=model,
        serial=serial,
        complectation=comp or None,
        fault_client=(form.get("fault_client") or "").strip() or None,
        condition_notes=condition_notes,
        master_id=master_id,
        consent_repair=bool(form.get("consent_repair")),
        is_delivery=is_delivery,
        delivery_district=delivery_district,
        delivery_comment=delivery_comment,
    )
