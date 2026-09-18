"""Business-rule settings stored in DB (never hardcoded).

Default keys:
- storage_months: int (default 3)
- legal_text: str  (the full "storage 3 months" legal text shown on blank/QR)
- sla_defaults: dict
- brand: str
- repair_statuses: list[str]
- printer: очередь CUPS для бланков A4
- label_printer: очередь CUPS для этикеток 58×38 мм
"""
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DEFAULT_REPAIR_STATUSES, Setting, map_status
from app.services.sms import DEFAULT_PICKUP_REMINDER_TEXT

# Как print-agent доставляет документ до принтера:
#   cups_local  — очередь в CUPS на самом сервере MSB (нужно только имя очереди);
#   cups_remote — очередь расшарена CUPS на другом компьютере (ip + порт 631);
#   agent       — драйвером ОС (SumatraPDF на Windows, иначе `lp` + MSB_PRINT_CMD);
#   ipp         — напрямую по IPP/AirPrint на http://IP:631/ipp/print.
PRINTER_MODES = ("cups_local", "cups_remote", "agent", "ipp")
# Этикетки: raw_tspl — принтер не в CUPS, слушает порт 9100 и читает TSPL,
# агент отправляет монохромный растр напрямую; cups_local/cups_remote — PDF в
# очередь CUPS (если термопринтер подключён к CUPS).
LABEL_PRINTER_MODES = ("raw_tspl", "cups_local", "cups_remote")

# Обе очереди живут в CUPS самого сервера MSB (`lpstat -p`):
#   office_printer_a4 — бланки A4;
#   3B-350B           — этикетки 58×38 мм.
# Имя очереди — не адрес: если его нет в CUPS, печать падает с явной ошибкой и
# списком доступных очередей, поэтому значение по умолчанию безопасно.
# Переопределяется env MSB_PRINTER_A4 / MSB_PRINTER_LABEL и в «Админ → Принтер».
DEFAULT_A4_QUEUE = os.environ.get("MSB_PRINTER_A4", "office_printer_a4")
DEFAULT_LABEL_QUEUE = os.environ.get("MSB_PRINTER_LABEL", "3B-350B")
# Принтер этикеток не в CUPS: raw-сокет 9100, язык TSPL. Адрес/порт переопределяются
# env MSB_LABEL_HOST / MSB_LABEL_PORT и в «Админ → Принтер».
DEFAULT_LABEL_HOST = os.environ.get("MSB_LABEL_HOST", "192.168.8.75")
DEFAULT_LABEL_PORT = int(os.environ.get("MSB_LABEL_PORT", "9100"))

# Названия A4-принтера из прошлой схемы (Epson L3250 по USB на рабочей машине).
# На сервере такой очереди нет, поэтому они считаются устаревшими.
LEGACY_A4_NAMES = ("", "epson l3250", "epson_l3250")

DEFAULT_SETTINGS: dict[str, dict] = {
    "storage_months": {
        "value": {"months": 3},
        "description": "Срок хранения техники после готовности (месяцев)",
    },
    "public_intake": {
        "value": {"enabled": True, "code": ""},
        "description": (
            "Приёмка без аккаунта: страница /intake, куда технику может оформить "
            "любой человек без входа. Ремонты попадают в «Новые», мастера берут "
            "их сами или назначает администратор. code — необязательный код "
            "доступа: если задан, страницу откроет только тот, кто его знает."
        ),
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
        "value": {"items": list(DEFAULT_REPAIR_STATUSES)},
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
        # Очередь CUPS на сервере MSB для бланков A4.
        "value": {"ip": "", "port": 631, "mode": "cups_local", "name": DEFAULT_A4_QUEUE},
        "description": "Принтер бланков A4: очередь CUPS (cups_local|cups_remote|agent|ipp)",
    },
    "label_printer": {
        # Принтер этикеток 58×38 мм. По умолчанию — raw-сокет TSPL на 9100
        # (принтер не в CUPS): нужны ip и порт. Для CUPS-режимов (cups_local /
        # cups_remote) вместо адреса используется имя очереди.
        "value": {
            "ip": DEFAULT_LABEL_HOST,
            "port": DEFAULT_LABEL_PORT,
            "mode": "raw_tspl",
            "name": DEFAULT_LABEL_QUEUE,
            "width_mm": 58,
            "height_mm": 38,
            "gap_mm": 2,
            "media": "Custom.58x38mm",
        },
        "description": "Принтер этикеток 58×38 мм (raw TSPL или CUPS)",
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
        # Старые настройки могли остаться в БД со списком из десяти статусов.
        # Приводим их к актуальным пяти (и убираем дубли), иначе удалённые
        # статусы продолжали бы предлагаться в селекторах.
        cleaned: list[str] = []
        for raw in items:
            name = str(raw).strip()
            if not name:
                continue
            name = map_status(name) or name
            if name not in cleaned:
                cleaned.append(name)
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
    """Настройки принтера бланков A4.

    По умолчанию — очередь `office_printer_a4` в CUPS самого сервера MSB:
    print-agent и API работают на одной машине с CUPS, поэтому адрес и порт не
    нужны. Режимы `cups_remote`/`ipp` оставлены для принтера на другом
    компьютере, `agent` — для печати драйвером ОС (Windows/SumatraPDF).
    """
    value = dict(DEFAULT_SETTINGS["printer"]["value"])
    saved = await get_setting(db, "printer")
    if saved:
        value.update(saved)
    if value.get("mode") not in PRINTER_MODES:
        value["mode"] = "cups_local"
    if not str(value.get("name") or "").strip():
        # Пустое имя означает «очередь не задана»: подставляем очередь сервера,
        # иначе агент печатал бы на принтер по умолчанию CUPS (этикеточный).
        value["name"] = DEFAULT_A4_QUEUE
    return value


async def get_label_printer(db: AsyncSession) -> dict:
    """Настройки принтера этикеток 58×38 мм.

    Режимы:
      raw_tspl    — принтер не в CUPS: слушает `ip:port` (9100) и читает TSPL.
                    Агент собирает монохромный растр 58×38 и отправляет его
                    напрямую в сокет; PDF и CUPS не участвуют.
      cups_local  — очередь в CUPS на том же сервере, где работает print-agent.
                    Нужен только `name`; адрес принтера знает сам CUPS.
      cups_remote — очередь расшарена CUPS на другом компьютере: нужны
                    `ip`, `port` (порт CUPS, 631) и `name`.

    Размер этикетки фиксирован носителем (58×38 мм) и не настраивается.
    """
    value = dict(DEFAULT_SETTINGS["label_printer"]["value"])
    saved = await get_setting(db, "label_printer")
    if saved:
        value.update(saved)
    if value.get("mode") not in LABEL_PRINTER_MODES:
        value["mode"] = "raw_tspl"
    if not str(value.get("name") or "").strip():
        value["name"] = DEFAULT_LABEL_QUEUE
    # raw-принтеру нужна точка подключения; CUPS-режимам — имя очереди.
    if value.get("mode") == "raw_tspl" and not str(value.get("ip") or "").strip():
        value["ip"] = DEFAULT_LABEL_HOST
    # Размер этикетки не настраивается — он определён физическим носителем.
    value.update(width_mm=58, height_mm=38)
    try:
        value["gap_mm"] = min(10.0, max(0.0, float(value.get("gap_mm", 2))))
    except (TypeError, ValueError):
        value["gap_mm"] = 2.0
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


async def get_public_intake(db) -> dict:
    """Приёмка без аккаунта: {"enabled": bool, "code": str}.

    `enabled` — доступна ли страница /intake; `code` — необязательный код
    доступа (пустой = страница открыта всем, кто знает адрес).
    """
    saved = await get_setting(db, "public_intake")
    data = saved or {}
    default = DEFAULT_SETTINGS["public_intake"]["value"]
    return {
        "enabled": bool(data.get("enabled", default["enabled"])),
        "code": str(data.get("code") or "").strip(),
    }


async def get_intake_auto_print(db) -> str:
    """Что печатать автоматически при приёмке: label / blank / both / none.

    По умолчанию — этикетка 58×38 (её клеят на технику при клиенте).
    """
    saved = await get_setting(db, "intake_auto_print")
    mode = (saved or {}).get("mode", "label")
    if mode not in ("label", "blank", "both", "none"):
        return "label"
    return mode
