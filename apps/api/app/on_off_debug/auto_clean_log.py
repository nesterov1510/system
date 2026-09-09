# ruff: noqa: BLE001, DTZ001, DTZ007, S112  -- порт из архива: широкий except и локальное время — намеренно
# on_off_debug/auto_clean_log.py
import calendar
import os
import re
import time
from datetime import datetime, timedelta

from app.on_off_debug.env_tools import (
    env_bool,
    env_int,
    read_env_file,
    resolve_log_dir,
)
from app.on_off_debug.internal_logger import write_internal_error
from app.on_off_debug.time_utils import from_ts, local_now

DEFAULT_AUTO_CLEAN_ENABLED = True
DEFAULT_CLEAN_ON_START = True
DEFAULT_CLEAN_AFTER_WRITE = True
DEFAULT_CLEAN_CHECK_INTERVAL_SECONDS = 3600
DEFAULT_LOG_RETENTION = "3 months"

BASE_LOG_DIR = ""
AUTO_CLEAN_ENABLED = DEFAULT_AUTO_CLEAN_ENABLED
CLEAN_ON_START = DEFAULT_CLEAN_ON_START
CLEAN_AFTER_WRITE = DEFAULT_CLEAN_AFTER_WRITE
CLEAN_CHECK_INTERVAL_SECONDS = DEFAULT_CLEAN_CHECK_INTERVAL_SECONDS
LOG_RETENTION = DEFAULT_LOG_RETENTION

_CLEAN_LAST_RUN_TS = 0.0
_CLEAN_IN_PROGRESS = False
_LOG_LINE_TIME_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]")


def reload_auto_clean_config() -> None:
    """
    Перезагружает настройки очистки из debug_module.env.

    DEBUG_NAME_APP нужен только для critical-уведомлений,
    имя приложения НЕ используется для папок логов.
    """
    global BASE_LOG_DIR
    global AUTO_CLEAN_ENABLED
    global CLEAN_ON_START
    global CLEAN_AFTER_WRITE
    global CLEAN_CHECK_INTERVAL_SECONDS
    global LOG_RETENTION

    env_data = read_env_file()

    BASE_LOG_DIR = resolve_log_dir(env_data)

    AUTO_CLEAN_ENABLED = env_bool(
        env_data, "DEBUG_AUTO_CLEAN_ENABLED", DEFAULT_AUTO_CLEAN_ENABLED
    )
    CLEAN_ON_START = env_bool(env_data, "DEBUG_CLEAN_ON_START", DEFAULT_CLEAN_ON_START)
    CLEAN_AFTER_WRITE = env_bool(
        env_data, "DEBUG_CLEAN_AFTER_WRITE", DEFAULT_CLEAN_AFTER_WRITE
    )
    CLEAN_CHECK_INTERVAL_SECONDS = env_int(
        env_data,
        "DEBUG_CLEAN_CHECK_INTERVAL_SECONDS",
        DEFAULT_CLEAN_CHECK_INTERVAL_SECONDS,
    )
    LOG_RETENTION = env_data.get("DEBUG_LOG_RETENTION", DEFAULT_LOG_RETENTION)


def _subtract_months(dt: datetime, months: int) -> datetime:
    total_months = dt.year * 12 + dt.month - 1
    total_months -= months

    year = total_months // 12
    month = total_months % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)

    return dt.replace(year=year, month=month, day=day)


def _get_retention_cutoff(now: datetime | None = None) -> datetime:
    if now is None:
        now = local_now()

    raw_value = str(LOG_RETENTION or DEFAULT_LOG_RETENTION).strip().lower()
    raw_value = raw_value.replace("_", " ").replace("-", " ")

    if raw_value.isdigit():
        return now - timedelta(days=int(raw_value))

    match = re.match(r"^\s*(\d+)\s*([a-zа-яё]+)\s*$", raw_value)

    if not match:
        return _subtract_months(now, 3)

    amount = int(match.group(1))
    unit = match.group(2).strip().lower()

    second_units = {"second", "seconds", "sec", "secs", "s", "секунда", "секунды", "секунд", "сек"}
    minute_units = {"minute", "minutes", "min", "mins", "минута", "минуты", "минут", "мин"}
    hour_units = {"hour", "hours", "h", "час", "часа", "часов"}
    day_units = {"day", "days", "d", "день", "дня", "дней", "сутки", "суток"}
    week_units = {"week", "weeks", "w", "неделя", "недели", "недель"}
    month_units = {"month", "months", "mon", "mons", "mo", "месяц", "месяца", "месяцев"}

    if unit in second_units:
        return now - timedelta(seconds=amount)
    if unit in minute_units:
        return now - timedelta(minutes=amount)
    if unit in hour_units:
        return now - timedelta(hours=amount)
    if unit in day_units:
        return now - timedelta(days=amount)
    if unit in week_units:
        return now - timedelta(weeks=amount)
    if unit in month_units:
        return _subtract_months(now, amount)

    return _subtract_months(now, 3)


def _find_log_date_from_path(file_path: str):
    normalized = os.path.normpath(file_path)
    parts = normalized.split(os.sep)

    for part in reversed(parts):
        try:
            return datetime.strptime(part, "%d.%m.%Y").date()
        except Exception:
            continue

    return None


def _cleanup_single_log_file(file_path: str, cutoff: datetime) -> None:
    try:
        log_date = _find_log_date_from_path(file_path)

        if log_date is None:
            modified_at = from_ts(os.path.getmtime(file_path))
            if modified_at < cutoff:
                os.remove(file_path)
            return

        file_start = datetime(log_date.year, log_date.month, log_date.day, 0, 0, 0)
        file_end = datetime(log_date.year, log_date.month, log_date.day, 23, 59, 59)

        if file_end < cutoff:
            os.remove(file_path)
            return

        if file_start >= cutoff:
            return

        kept_lines = []

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        for line in lines:
            match = _LOG_LINE_TIME_RE.match(line)

            if not match:
                kept_lines.append(line)
                continue

            hour = int(match.group(1))
            minute = int(match.group(2))
            second = int(match.group(3))
            line_dt = datetime(log_date.year, log_date.month, log_date.day, hour, minute, second)

            if line_dt >= cutoff:
                kept_lines.append(line)

        if kept_lines:
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(kept_lines)
        else:
            os.remove(file_path)

    except FileNotFoundError:
        return
    except Exception as e:
        write_internal_error("auto_clean_log._cleanup_single_log_file", f"{file_path} | {e}")


def _remove_empty_dirs(base_dir: str) -> None:
    if not base_dir or not os.path.exists(base_dir):
        return

    for root, dirs, files in os.walk(base_dir, topdown=False):
        if root == base_dir:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except Exception as e:
            write_internal_error("auto_clean_log._remove_empty_dirs", f"{root} | {e}")


def cleanup_old_logs(force: bool = False) -> None:
    """Очищает старые логи. Управляется через debug_module.env."""
    global _CLEAN_LAST_RUN_TS
    global _CLEAN_IN_PROGRESS

    reload_auto_clean_config()

    if not AUTO_CLEAN_ENABLED or _CLEAN_IN_PROGRESS:
        return

    now_ts = time.time()

    if not force:
        elapsed = now_ts - _CLEAN_LAST_RUN_TS
        if elapsed < CLEAN_CHECK_INTERVAL_SECONDS:
            return

    if not BASE_LOG_DIR or not os.path.exists(BASE_LOG_DIR):
        return

    _CLEAN_IN_PROGRESS = True

    try:
        cutoff = _get_retention_cutoff(local_now())

        for root, dirs, files in os.walk(BASE_LOG_DIR):
            for filename in files:
                file_path = os.path.join(root, filename)
                if os.path.isfile(file_path):
                    _cleanup_single_log_file(file_path, cutoff)

        _remove_empty_dirs(BASE_LOG_DIR)
        _CLEAN_LAST_RUN_TS = now_ts

    except Exception as e:
        write_internal_error("auto_clean_log.cleanup_old_logs", str(e))

    finally:
        _CLEAN_IN_PROGRESS = False


def maybe_cleanup_old_logs() -> None:
    reload_auto_clean_config()

    if not CLEAN_AFTER_WRITE:
        return

    cleanup_old_logs(force=False)


def clean_on_start_if_enabled() -> None:
    reload_auto_clean_config()

    if not CLEAN_ON_START:
        return

    cleanup_old_logs(force=True)


reload_auto_clean_config()
