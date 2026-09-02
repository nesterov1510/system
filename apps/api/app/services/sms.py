"""SMS-уведомления через шлюз на 192.168.8.81.

Параметры шлюза заданы дефолтом в `app.core.config.Settings` (прямо в коде —
см. задачу), при желании переопределяются через env. Шлюз слушает по HTTPS с
самоподписанным сертификатом, поэтому запросы идут с `verify=False` (как `curl -k`).

Пример вызова шлюза:
    POST https://192.168.8.81/api/3rdparty/v1/messages
    basic-auth  KJV7XJ : fbsybvpoothupl
    {"textMessage": {"text": "..."}, "phoneNumbers": ["+993..."]}

Любая отправка не должна ронять основной поток (назначение ремонта, смена
статуса и т.п.): при недоступности шлюза мы логируем и возвращаем {"ok": False}.
"""
import logging

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


def build_master_sms(master_name: str, repair) -> str:
    """Шаблон авто-SMS мастеру при назначении на ремонт (все данные ремонта)."""
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


def build_ready_sms(repair) -> str:
    """Шаблон SMS клиенту о готовности ремонта («Ремонт закончен»)."""
    client_name = repair.client.full_name if repair.client else ""
    device = device_line(repair.brand, repair.model, repair.device_type)
    msg = (
        f"Здравствуйте, {client_name}! Ваша {device} по заказу № {repair.number} "
        f"отремонтирована и готова к выдаче. Будем рады видеть вас в сервисном центре."
    )
    return msg.strip()


def sms_enabled() -> bool:
    return bool(settings.SMS_ENABLED)


async def send_sms(phone: str, text: str) -> dict:
    """Отправить одно SMS. Возвращает {"ok": bool, "detail": str}.

    Ошибка шлюза/сети никогда не поднимает исключение наружу.
    """
    if not sms_enabled():
        return {"ok": False, "detail": "sms_disabled"}
    to = _gateway_phone(phone)
    if not to:
        return {"ok": False, "detail": "no_phone"}

    payload = {"textMessage": {"text": text}, "phoneNumbers": [to]}
    try:
        async with httpx.AsyncClient(
            verify=settings.SMS_VERIFY_SSL,
            timeout=settings.SMS_TIMEOUT_SEC,
        ) as client:
            resp = await client.post(
                settings.SMS_GATEWAY_URL,
                json=payload,
                auth=(settings.SMS_GATEWAY_USERNAME, settings.SMS_GATEWAY_PASSWORD),
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


async def send_master_assignment_sms(master, repair) -> dict:
    """Авто-SMS мастеру при назначении (если у мастера указан телефон)."""
    if not master.phone:
        return {"ok": False, "detail": "no_master_phone"}
    text = build_master_sms(master.name, repair)
    return await send_sms(master.phone, text)
