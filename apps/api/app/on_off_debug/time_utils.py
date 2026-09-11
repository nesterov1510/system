# ruff: noqa: DTZ005, DTZ006  -- fallback-ветки без tz намеренно: используются только когда zoneinfo недоступен
# on_off_debug/time_utils.py
"""
Единое время для всего debug-модуля.

Все метки и папки дат должны жить в часовом поясе офиса (Asia/Ashgabat),
а не в локальном времени сервера — иначе мониторинг логов покажет даты,
не совпадающие с остальной системой.

Возвращаем naive datetime намеренно: все сравнения дат внутри модуля тоже
naive, а `tzinfo=None` после `ZoneInfo` сохраняет правильное настенное время.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    APP_TZ = ZoneInfo("Asia/Ashgabat")
except Exception:  # noqa: BLE001 — fallback на локальное время, если zoneinfo недоступен
    APP_TZ = None


def local_now() -> datetime:
    """Текущее настенное время в Asia/Ashgabat (naive)."""
    if APP_TZ is not None:
        return datetime.now(APP_TZ).replace(tzinfo=None)
    return datetime.now()


def from_ts(ts: float) -> datetime:
    """mtime файла -> настенное время в Asia/Ashgabat (naive)."""
    if APP_TZ is not None:
        return datetime.fromtimestamp(ts, APP_TZ).replace(tzinfo=None)
    return datetime.fromtimestamp(ts)
