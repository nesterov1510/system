"""SMS-уведомления через настраиваемый в админке шлюз.

Параметры шлюза (URL, логин/пароль, вкл/выкл) и тексты шаблонов хранятся в БД
(`Setting` — ключи `sms_server` и `sms_templates`, см. `app.services.settings`)
и редактируются в админ-панели. Дефолты в `app.core.config.Settings` остаются
только как fallback на случай пустой БД (например, для юнит-тестов, где не
передаётся `db`).

Шлюз слушает по HTTPS с самоподписанным сертификатом по умолчанию, поэтому
запросы могут идти с `verify=False` (как `curl -k`), если это так настроено:
    POST https://<ip>/api/3rdparty/v1/messages
    basic-auth  <login> : <password>
    {"textMessage": {"text": "..."}, "phoneNumbers": ["+993..."]}

Любая отправка не должна ронять основной поток (назначение ремонта, смена
статуса и т.п.): при недоступности шлюза мы логируем и возвращаем {"ok": False}.
"""
import logging
from collections import defaultdict

import httpx

from app.core.config import settings

logger = logging.getLogger("msb.sms")


def _gateway_phone(phone: str) -> str:
    """Привести телефон к виду, который принимает шлюз (+993..., без пробелов)."""
    clean = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    clean = clean.replace("++", "+")
    if not clean:
        return ""
    if not clean.startswith("+"):
        clean = "+" + clean
    return clean


def device_line(brand, model, device_type: str) -> str:
    """«ТВ Samsung UE55» — краткое описание техники для SMS."""
    parts = [p for p in (brand, model) if p]
    if parts:
        return f"{device_type} {' '.join(parts)}".strip()
    return device_type or "техника"


def _safe_format(template: str, tokens: dict) -> str:
    """str.format, но неизвестные/пустые плейсхолдеры не роняют отправку."""
    return template.format_map(defaultdict(str, tokens))


def master_sms_tokens(master_name: str, repair) -> dict:
    """Плейсхолдеры, доступные в шаблоне SMS мастеру."""
    return {
        "master_name": master_name or "",
        "number": getattr(repair, "number", "") or "",
        "device": device_line(
            getattr(repair, "brand", None),
            getattr(repair, "model", None),
            getattr(repair, "device_type", "") or "",
        ),
        "serial": getattr(repair, "serial", None) or "",
        "client_name": (repair.client.full_name if getattr(repair, "client", None) else ""),
        "client_phone": (
            (repair.client.phone or "") if getattr(repair, "client", None) else ""
        ),
        "fault": getattr(repair, "fault_client", None) or "",
        "eta_days": getattr(repair, "eta_days", None) or "",
    }


def ready_sms_tokens(repair) -> dict:
    """Плейсхолдеры, доступные в шаблоне SMS клиенту о готовности."""
    return {
        "client_name": (repair.client.full_name if getattr(repair, "client", None) else ""),
        "number": getattr(repair, "number", "") or "",
        "device": device_line(
            getattr(repair, "brand", None),
            getattr(repair, "model", None),
            getattr(repair, "device_type", "") or "",
        ),
    }


AVAILABLE_MASTER_FIELDS = [
    "master_name",
    "number",
    "device",
    "serial",
    "client_name",
    "client_phone",
    "fault",
    "eta_days",
]
AVAILABLE_READY_FIELDS = ["client_name", "number", "device"]


def build_master_sms(master_name: str, repair, template: str | None = None) -> str:
    """Текст авто-SMS мастеру при назначении на ремонт.

    Если `template` не задан (пусто в настройках) — используется дефолтный
    многострочный текст со всеми доступными данными ремонта.
    """
    if template:
        return _safe_format(template, master_sms_tokens(master_name, repair)).strip()
    lines = [
        f"Уважаемый(ая) {master_name}! Вам назначен ремонт.",
        f"№ {repair.number} · {device_line(repair.brand, repair.model, repair.device_type)}",
    ]
    if repair.serial:
        lines.append(f"Серийный №: {repair.serial}")
    if repair.client:
        line = f"Клиент: {repair.client.full_name}"
        if repair.client.phone:
            line += f", {repair.client.phone}"
        lines.append(line)
    if repair.fault_client:
        lines.append(f"Неисправность: {repair.fault_client}")
    if repair.eta_days:
        lines.append(f"Срок: ~{repair.eta_days} дн.")
    return "\n".join(lines)


def build_ready_sms(repair, template: str | None = None) -> str:
    """Текст SMS клиенту о готовности ремонта («Ремонт закончен»).

    Если `template` не задан (пусто в настройках) — используется дефолтный текст.
    """
    if template:
        return _safe_format(template, ready_sms_tokens(repair)).strip()
    client_name = repair.client.full_name if repair.client else ""
    device = device_line(repair.brand, repair.model, repair.device_type)
    msg = (
        f"Здравствуйте, {client_name}! Ваша {device} по заказу № {repair.number} "
        f"отремонтирована и готова к выдаче. Будем рады видеть вас в сервисном центре."
    )
    return msg.strip()


async def _gateway_config(db=None) -> dict:
    """Настройки шлюза: из БД (админка), с fallback на app.core.config.Settings."""
    if db is not None:
        from app.services.settings import get_sms_server

        cfg = await get_sms_server(db)
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "url": cfg.get("url") or settings.SMS_GATEWAY_URL,
            "username": cfg.get("username") or settings.SMS_GATEWAY_USERNAME,
            "password": cfg.get("password") or settings.SMS_GATEWAY_PASSWORD,
            "verify_ssl": bool(cfg.get("verify_ssl", settings.SMS_VERIFY_SSL)),
            "timeout_sec": float(cfg.get("timeout_sec") or settings.SMS_TIMEOUT_SEC),
        }
    # Без сессии БД (например, юнит-тесты чистых функций) — берём дефолты кода.
    return {
        "enabled": bool(settings.SMS_ENABLED),
        "url": settings.SMS_GATEWAY_URL,
        "username": settings.SMS_GATEWAY_USERNAME,
        "password": settings.SMS_GATEWAY_PASSWORD,
        "verify_ssl": bool(settings.SMS_VERIFY_SSL),
        "timeout_sec": float(settings.SMS_TIMEOUT_SEC),
    }


async def sms_enabled(db=None) -> bool:
    cfg = await _gateway_config(db)
    return bool(cfg["enabled"])


async def send_sms(phone: str, text: str, db=None) -> dict:
    """Отправить одно SMS. Возвращает {"ok": bool, "detail": str}.

    Ошибка шлюза/сети никогда не поднимает исключение наружу. Параметры шлюза
    берутся из настроек в БД (`db`, если передан), иначе — из дефолтов кода.
    """
    cfg = await _gateway_config(db)
    if not cfg["enabled"]:
        return {"ok": False, "detail": "sms_disabled"}
    to = _gateway_phone(phone)
    if not to:
        return {"ok": False, "detail": "no_phone"}
    if not cfg["url"]:
        return {"ok": False, "detail": "no_gateway_url"}

    payload = {"textMessage": {"text": text}, "phoneNumbers": [to]}
    try:
        async with httpx.AsyncClient(
            verify=cfg["verify_ssl"],
            timeout=cfg["timeout_sec"],
        ) as client:
            resp = await client.post(
                cfg["url"],
                json=payload,
                auth=(cfg["username"], cfg["password"]),
            )
        if resp.status_code < 300:
            return {"ok": True, "detail": f"http_{resp.status_code}"}
        logger.warning(
            "SMS gateway error: http_%s -> %s", resp.status_code, resp.text[:200]
        )
        return {"ok": False, "detail": f"http_{resp.status_code}"}
    except Exception as exc:  # noqa: BLE001 — шлюз не должен ронять основной поток
        logger.warning("SMS send failed to %s: %s", to, exc)
        return {"ok": False, "detail": f"{type(exc).__name__}"}


async def send_master_assignment_sms(master, repair, db=None) -> dict:
    """Авто-SMS мастеру при назначении (если у мастера указан телефон)."""
    if not master.phone:
        return {"ok": False, "detail": "no_master_phone"}
    template = None
    if db is not None:
        from app.services.settings import get_sms_templates

        tpl = await get_sms_templates(db)
        template = tpl.get("master_assign") or None
    text = build_master_sms(master.name, repair, template=template)
    return await send_sms(master.phone, text, db=db)
