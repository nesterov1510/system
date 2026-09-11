"""Business-rule settings stored in DB (never hardcoded).

Default keys:
- storage_months: int (default 3)
- legal_text: str  (the full "storage 3 months" legal text shown on blank/QR)
- sla_defaults: dict
- brand: str
- repair_statuses: list[str]
- printer: основной принтер бланков
- label_printer: удалённая CUPS-очередь для этикеток 58×38 мм
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting
from app.services.sms import DEFAULT_PICKUP_REMINDER_TEXT

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
    "print_stub": {
        "value": {
            # Заголовки и подписи отрывной части бланка A4 (талон клиента).
            # Редактируются администратором в /admin/settings → Печать.
            "title": "KLIENTE / ДЛЯ КЛИЕНТА",
            "terms_label": "Условия хранения:",
            "consent_label": "О ремонте:",
            "qr_caption": "Сканируйте — статус ремонта",
            "sign_client": "Подпись клиента",
            "sign_date": "Дата",
            "cut_hint": "— ✂ отрывная часть для клиента ✂ —",
        },
        "description": "Отрывная часть бланка A4 (талон клиента): заголовки и подписи",
    },
    "brand": {
        "value": {"name": "MSB"},
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
    "ip_control": {
        "value": {
            # off        — фильтр выключен, доступ открыт всем;
            # whitelist  — разрешены только перечисленные IP/сети (белый список);
            # blacklist  — запрещены перечисленные IP/сети (чёрный список).
            #
            # ПО УМОЛЧАНИЮ включён белый список с рабочими сетями офиса:
            # 192.168.5.0/24 (компьютеры) и 192.168.8.0/24 (сеть сервера) —
            # обе доступны сразу, остальные адреса админ открывает сам.
            "mode": "whitelist",
            "whitelist": ["192.168.5.0/24", "192.168.8.0/24"],
            "blacklist": [],
            # Доверять X-Forwarded-For (включать ТОЛЬКО за обратным прокси nginx).
            "trust_proxy": False,
        },
        "description": "Контроль доступа к интерфейсу по IP клиента (белый/чёрный список)",
    },
    "printer": {
        "value": {"ip": "", "port": 631, "mode": "agent", "name": ""},
        "description": "Основной принтер: имя, режим печати (agent|ipp)",
    },
    "label_printer": {
        # Адрес и имя очереди намеренно пустые: их задаёт администратор в
        # «Админ → Принтер». Хардкодить внутренний IP в коде нельзя — при
        # переносе на другой сервер этикетки молча уезжали бы не туда.
        "value": {
            "ip": "",
            "port": 631,
            "mode": "cups_remote",
            "name": "",
            "width_mm": 58,
            "height_mm": 38,
            "media": "Custom.58x38mm",
        },
        "description": "CUPS-принтер этикеток 58×38 мм",
    },
    "sms_server": {
        # URL/логин/пароль задаются в «Админ → SMS» или через env. В коде
        # боевых креденшелов и внутренних адресов быть не должно.
        "value": {
            "enabled": False,
            "url": "",
            "username": "",
            "password": "",
            "verify_ssl": True,
            "timeout_sec": 10.0,
        },
        "description": "SMS-шлюз: адрес, логин/пароль, таймаут",
    },
    "sms_templates": {
        "value": {
            "master_assign": "",
            "ready": "",
            # Ежедневное напоминание «заберите технику»: текст виден и правится
            # в «Админ → SMS», поэтому название сервиса и адрес здесь можно
            # поменять без правки кода.
            "pickup_reminder": DEFAULT_PICKUP_REMINDER_TEXT,
        },
        "description": (
            "Шаблоны текстов SMS (пусто = использовать текст по умолчанию). "
            "Доступные плейсхолдеры для шаблона мастеру: {master_name} {number} "
            "{device} {serial} {client_name} {client_phone} {fault} {eta_days}. "
            "Для шаблона клиенту о готовности: {client_name} {number} {device}. "
            "Для ежедневного напоминания забрать технику (pickup_reminder): "
            "{client_name} {number} {device} {days} {ready_date}."
        ),
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


async def get_repair_statuses(db: AsyncSession) -> list[str]:
    """Список допустимых статусов ремонта (настраивается в админке).

    Используется для валидации PATCH /repairs/{id}: произвольный статус
    ломал доску, очередь call-центра и статистику, потому что все они
    фильтруют по точному совпадению со строкой статуса.
    """
    s = await get_setting(db, "repair_statuses")
    items = (s or {}).get("items")
    if isinstance(items, list) and items:
        cleaned = [str(x).strip() for x in items if str(x).strip()]
        if cleaned:
            return cleaned
    return list(DEFAULT_SETTINGS["repair_statuses"]["value"]["items"])


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


async def get_label_printer(db: AsyncSession) -> dict:
    """Настройки удалённой CUPS-очереди для этикеток ремонта.

    Формат PDF и режим маршрутизации фиксированы требованиями этого принтера;
    из БД настраиваются только адрес, порт, очередь и media option.
    """
    value = dict(DEFAULT_SETTINGS["label_printer"]["value"])
    saved = await get_setting(db, "label_printer")
    if saved:
        value.update(saved)
    value.update(mode="cups_remote", width_mm=58, height_mm=38)
    return value


async def get_sms_server(db: AsyncSession) -> dict:
    """Настройки SMS-шлюза (URL, логин/пароль, таймаут)."""
    value = dict(DEFAULT_SETTINGS["sms_server"]["value"])
    saved = await get_setting(db, "sms_server")
    if saved:
        value.update(saved)
    return value


async def get_sms_templates(db: AsyncSession) -> dict:
    """Шаблоны текстов SMS (пустая строка = использовать текст по умолчанию)."""
    value = dict(DEFAULT_SETTINGS["sms_templates"]["value"])
    saved = await get_setting(db, "sms_templates")
    if saved:
        value.update(saved)
    return value


async def get_ip_control(db) -> dict:
    """Настройки IP-контроля доступа (белый/чёрный список IP клиентов).

    Возвращает dict: mode (off|whitelist|blacklist), whitelist, blacklist —
    списки строк (IP или CIDR-сети). Локальные адреса (127.0.0.1, ::1) всегда
    разрешены, чтобы администратор не заблокировал сам себя.
    """
    value = {
        # По умолчанию — белый список с рабочими сетями офиса (192.168.5.0/24 и
        # 192.168.8.0/24): они доступны сразу, остальное админ открывает сам.
        # Loopback разрешён всегда.
        "mode": "whitelist",
        "whitelist": ["192.168.5.0/24", "192.168.8.0/24"],
        "blacklist": [],
        "trust_proxy": False,
    }
    saved = await get_setting(db, "ip_control")
    if saved:
        if saved.get("mode") in ("off", "whitelist", "blacklist"):
            value["mode"] = saved["mode"]
        value["whitelist"] = [str(x).strip() for x in (saved.get("whitelist") or []) if str(x).strip()]
        value["blacklist"] = [str(x).strip() for x in (saved.get("blacklist") or []) if str(x).strip()]
        value["trust_proxy"] = bool(saved.get("trust_proxy"))
    return value


async def get_print_stub(db) -> dict:
    """Заголовки и подписи отрывной части бланка A4 (талон клиента).

    Редактируются администратором на вкладке «Печать» (/admin/settings).
    """
    value = {
        "title": "KLIENTE / ДЛЯ КЛИЕНТА",
        "terms_label": "Условия хранения:",
        "consent_label": "О ремонте:",
        "qr_caption": "Сканируйте — статус ремонта",
        "sign_client": "Подпись клиента",
        "sign_date": "Дата",
        "cut_hint": "— ✂ отрывная часть для клиента ✂ —",
    }
    saved = await get_setting(db, "print_stub")
    if saved:
        for key in value:
            val = (saved.get(key) or "").strip()
            if val:
                value[key] = val
    return value


async def get_intake_auto_print(db) -> str:
    """Что печатать автоматически при приёмке: label / blank / both / none.

    По умолчанию — этикетка 58×38 (её клеят на технику при клиенте).
    """
    saved = await get_setting(db, "intake_auto_print")
    mode = (saved or {}).get("mode", "label")
    if mode not in ("label", "blank", "both", "none"):
        return "label"
    return mode
