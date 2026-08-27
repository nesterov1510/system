"""Business-rule settings stored in DB (never hardcoded).

Default keys:
- storage_months: int (default 3)
- legal_text: str  (the full "storage 3 months" legal text shown on blank/QR)
- sla_defaults: dict
- brand: str
- repair_statuses: list[str]
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting

DEFAULT_SETTINGS: dict[str, dict] = {
    "storage_months": {
        "value": {"months": 3},
        "description": "Срок хранения техники после готовности (месяцев)",
    },
    "legal_text": {
        "value": {
            "text": (
                "Техника хранится в сервисном центре бесплатно в течение 3 (трёх) "
                "месяцев с момента уведомления о готовности. По истечении этого "
                "срока сервисный центр вправе реализовать технику в порядке, "
                "предусмотренном законодательством."
            )
        },
        "description": "Юридический текст про хранение 3 месяца",
    },
    "consent_repair_text": {
        "value": {
            "text": (
                "Я, заказчик, даю согласие на проведение диагностики и ремонта "
                "переданного устройства, включая его разборку, замену компонентов "
                "и использование совместимых запасных частей. Я подтверждаю, что "
                "предоставил достоверные сведения об устройстве и ознакомлен с "
                "условиями хранения и оплаты. Согласие на обработку персональных "
                "данных получено."
            )
        },
        "description": "Юридический текст согласия на диагностику и ремонт",
    },
    "brand": {
        "value": {"name": "MSB — Мастер Сервис Бюро"},
        "description": "Название сервисного центра",
    },
    "repair_statuses": {
        "value": {
            "items": [
                "Принято",
                "Диагностика",
                "Согласование",
                "Ожидание запчастей",
                "В ремонте",
                "Готово к выдаче",
                "Выдано",
                "Не забрано",
                "Архив",
                "Отказ",
            ]
        },
        "description": "Список статусов ремонта (настраиваемый)",
    },
    "sms_enabled": {"value": {"enabled": False}, "description": "SMS-уведомления клиенту"},
    "print_mode": {
        "value": {"mode": "pdf"},
        "description": "Режим печати: pdf (A4) | escpos (термопринтер)",
    },
    "currency": {
        "value": {"code": "TMT", "symbol": "ман.", "decimals": 0},
        "description": "Валюта: туркменский манат (TMT)",
    },
    "region": {
        "value": {"country": "Туркменистан", "timezone": "Asia/Ashgabat"},
        "description": "Регион развёртывания",
    },
    "printer": {
        "value": {"ip": "", "port": 631, "mode": "agent", "name": "Epson L3250"},
        "description": "Принтер: IP-адрес, порт, режим печати (agent|ipp)",
    },
}


async def get_setting(db: AsyncSession, key: str, default: dict | None = None) -> dict | None:
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None:
        return default
    return setting.value


async def set_setting(db: AsyncSession, key: str, value: dict, description: str | None = None):
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None:
        setting = Setting(key=key, value=value, description=description)
        db.add(setting)
    else:
        setting.value = value
        if description is not None:
            setting.description = description
    await db.commit()
    return setting


async def get_storage_months(db: AsyncSession) -> int:
    s = await get_setting(db, "storage_months")
    if s and isinstance(s.get("months"), int):
        return s["months"]
    return 3


async def get_legal_text(db: AsyncSession) -> str:
    s = await get_setting(db, "legal_text")
    if s and s.get("text"):
        return s["text"]
    return DEFAULT_SETTINGS["legal_text"]["value"]["text"]


async def get_currency(db: AsyncSession) -> dict:
    s = await get_setting(db, "currency")
    if s:
        return s
    return DEFAULT_SETTINGS["currency"]["value"]


async def get_consent_repair_text(db: AsyncSession) -> str:
    s = await get_setting(db, "consent_repair_text")
    if s and s.get("text"):
        return s["text"]
    return DEFAULT_SETTINGS["consent_repair_text"]["value"]["text"]


async def get_printer(db: AsyncSession) -> dict:
    s = await get_setting(db, "printer")
    if s:
        return s
    return DEFAULT_SETTINGS["printer"]["value"]
