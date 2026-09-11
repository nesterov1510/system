# ruff: noqa: BLE001, S110  -- порт из архива: широкий except — намеренно
# on_off_debug/internal_logger.py
import os

from app.on_off_debug.time_utils import local_now

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTERNAL_LOG_DIR = os.path.join(BASE_DIR, "internal_log_folder")


def write_internal_error(source: str, message: str) -> None:
    """
    Аварийный внутренний лог самого debug-модуля.
    Здесь нельзя использовать debug_error_print(), чтобы не получить круговую ошибку.
    """
    try:
        today = local_now().strftime("%d.%m.%Y")
        log_dir = os.path.join(INTERNAL_LOG_DIR, "internal_error", today)
        os.makedirs(log_dir, exist_ok=True)

        log_path = os.path.join(log_dir, "internal_error.log")
        timestamp = local_now().strftime("%H:%M:%S")

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{source}] {message}\n")

    except Exception:
        pass
