# ruff: noqa: BLE001  -- порт из архива: широкий except — намеренно (модуль не должен ронять приложение)
# on_off_debug/debug_mode.py
import atexit
import os
import queue
import sys
import threading

from app.on_off_debug.auto_clean_log import (
    clean_on_start_if_enabled,
    maybe_cleanup_old_logs,
)
from app.on_off_debug.critical_notify import send_critical_notification
from app.on_off_debug.env_tools import (
    env_bool,
    env_str,
    get_auto_ip,
    read_env_file,
    resolve_log_dir,
)
from app.on_off_debug.internal_logger import write_internal_error
from app.on_off_debug.time_utils import local_now

# ==========================================================
# Base paths
# ==========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ==========================================================
# Default App Identity
# Эти данные НЕ вставляются в обычные логи.
# Они используются только для critical-уведомлений.
# ==========================================================

DEFAULT_DEBUG_NAME_APP = "unknown_app"
DEFAULT_DEBUG_APP_IP = "auto"
DEFAULT_DEBUG_APP_ENV = "local"
DEFAULT_DEBUG_APP_INSTANCE = "main"


# ==========================================================
# Default Debug Modes
# ==========================================================

DEFAULT_DEBUG_INFO_MODE = True
DEFAULT_DEBUG_SUCCESS_MODE = True
DEFAULT_DEBUG_SUCCESS1_MODE = True
DEFAULT_DEBUG_WARNING_MODE = True
DEFAULT_DEBUG_ERROR_MODE = True
DEFAULT_DEBUG_ERROR1_MODE = True
DEFAULT_DEBUG_CRITICAL_ERROR_MODE = True
DEFAULT_DEBUG_UNICODE_MODE = True
DEFAULT_DEBUG_RELOAD_ENV_EACH_CALL = True

# Отдельные тумблеры HTTP-логирования (не связаны с DEBUG_INFO_MODE):
DEFAULT_DEBUG_HTTP_LOG_MODE = True   # писать HTTP-запросы в журнал
DEFAULT_DEBUG_HTTP_CONSOLE = False   # дублировать их в консоль (шумно)

# Ротация лог-файлов по размеру.
DEFAULT_DEBUG_MAX_FILE_KB = 2048
DEFAULT_DEBUG_MAX_FILES = 5


# ==========================================================
# Working App Identity (загружаются из debug_module.env)
# ==========================================================

DEBUG_NAME_APP = DEFAULT_DEBUG_NAME_APP
DEBUG_APP_IP = DEFAULT_DEBUG_APP_IP
DEBUG_APP_ENV = DEFAULT_DEBUG_APP_ENV
DEBUG_APP_INSTANCE = DEFAULT_DEBUG_APP_INSTANCE


# ==========================================================
# Working Debug Modes (загружаются из debug_module.env)
# ==========================================================

DEBUG_INFO_MODE = DEFAULT_DEBUG_INFO_MODE
DEBUG_SUCCESS_MODE = DEFAULT_DEBUG_SUCCESS_MODE
DEBUG_SUCCESS1_MODE = DEFAULT_DEBUG_SUCCESS1_MODE
DEBUG_WARNING_MODE = DEFAULT_DEBUG_WARNING_MODE
DEBUG_ERROR_MODE = DEFAULT_DEBUG_ERROR_MODE
DEBUG_ERROR1_MODE = DEFAULT_DEBUG_ERROR1_MODE
DEBUG_CRITICAL_ERROR_MODE = DEFAULT_DEBUG_CRITICAL_ERROR_MODE
DEBUG_UNICODE_MODE = DEFAULT_DEBUG_UNICODE_MODE
DEBUG_RELOAD_ENV_EACH_CALL = DEFAULT_DEBUG_RELOAD_ENV_EACH_CALL

DEBUG_HTTP_LOG_MODE = DEFAULT_DEBUG_HTTP_LOG_MODE
DEBUG_HTTP_CONSOLE = DEFAULT_DEBUG_HTTP_CONSOLE
DEBUG_MAX_FILE_KB = DEFAULT_DEBUG_MAX_FILE_KB
DEBUG_MAX_FILES = DEFAULT_DEBUG_MAX_FILES


# ==========================================================
# Log folder
# ==========================================================

BASE_LOG_DIR = os.path.join(BASE_DIR, "log_folder")


# ==========================================================
# Фоновый поток записи (чтобы файловый I/O не блокировал event loop)
# ==========================================================

_WRITE_QUEUE: queue.Queue = queue.Queue(maxsize=20000)
_WRITER_THREAD: threading.Thread | None = None
_WRITER_LOCK = threading.Lock()


def _log_path(subfolder: str, filename: str) -> str:
    today = local_now().strftime("%d.%m.%Y")
    return os.path.join(BASE_LOG_DIR, subfolder, today, filename)


def _rotate_if_needed(log_path: str, max_kb: int, max_files: int) -> None:
    """Ротация по размеру: log -> log.1 -> log.2 -> ..."""
    if max_kb <= 0 or max_files <= 0:
        return
    try:
        if not os.path.exists(log_path):
            return
        if os.path.getsize(log_path) < max_kb * 1024:
            return
        base, ext = os.path.splitext(log_path)
        for i in range(max_files - 1, 0, -1):
            src = f"{base}.{i}{ext}"
            dst = f"{base}.{i + 1}{ext}"
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(log_path, f"{base}.1{ext}")
    except Exception as e:
        write_internal_error("debug_mode._rotate_if_needed", str(e))


def _file_write_now(subfolder: str, filename: str, message: str) -> str:
    """Непосредственная запись строки в файл (выполняется в потоке-писателе)."""
    log_path = _log_path(subfolder, filename)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    _rotate_if_needed(log_path, DEBUG_MAX_FILE_KB, DEBUG_MAX_FILES)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{local_now().strftime('%H:%M:%S')}] {message}\n")
    maybe_cleanup_old_logs()
    return log_path


def _writer_loop() -> None:
    while True:
        item = _WRITE_QUEUE.get()
        if item is None:  # сигнал остановки
            return
        subfolder, filename, message = item
        try:
            _file_write_now(subfolder, filename, message)
        except Exception as e:
            write_internal_error("debug_mode._writer_loop", str(e))


def _ensure_writer() -> None:
    global _WRITER_THREAD
    with _WRITER_LOCK:
        if _WRITER_THREAD is None or not _WRITER_THREAD.is_alive():
            _WRITER_THREAD = threading.Thread(
                target=_writer_loop, daemon=True, name="msb-debug-writer"
            )
            _WRITER_THREAD.start()


def flush_log_writes() -> None:
    """Дописать очередь перед остановкой приложения."""
    try:
        while True:
            item = _WRITE_QUEUE.get_nowait()
            if item is None:
                continue
            subfolder, filename, message = item
            try:
                _file_write_now(subfolder, filename, message)
            except Exception as e:
                write_internal_error("debug_mode.flush_log_writes", str(e))
    except queue.Empty:
        pass


atexit.register(flush_log_writes)


def _resolve_app_ip(value: str) -> str:
    """
    Возвращает IP приложения/сервера для critical-уведомлений.

    DEBUG_APP_IP=auto -> модуль определит локальный IP сам.
    DEBUG_APP_IP=192.168.8.9 -> будет использовано указанное значение.
    """
    value = str(value or "").strip()

    if not value or value.lower() == "auto":
        return get_auto_ip()

    return value


def reload_debug_config() -> None:
    """Перезагружает настройки debug из debug_module.env."""
    global DEBUG_NAME_APP
    global DEBUG_APP_IP
    global DEBUG_APP_ENV
    global DEBUG_APP_INSTANCE

    global DEBUG_INFO_MODE
    global DEBUG_SUCCESS_MODE
    global DEBUG_SUCCESS1_MODE
    global DEBUG_WARNING_MODE
    global DEBUG_ERROR_MODE
    global DEBUG_ERROR1_MODE
    global DEBUG_CRITICAL_ERROR_MODE
    global DEBUG_UNICODE_MODE
    global DEBUG_RELOAD_ENV_EACH_CALL
    global DEBUG_HTTP_LOG_MODE
    global DEBUG_HTTP_CONSOLE
    global DEBUG_MAX_FILE_KB
    global DEBUG_MAX_FILES

    global BASE_LOG_DIR

    env_data = read_env_file()

    # App identity — только для critical-уведомлений.
    DEBUG_NAME_APP = env_str(env_data, "DEBUG_NAME_APP", DEFAULT_DEBUG_NAME_APP)
    DEBUG_APP_IP = _resolve_app_ip(env_str(env_data, "DEBUG_APP_IP", DEFAULT_DEBUG_APP_IP))
    DEBUG_APP_ENV = env_str(env_data, "DEBUG_APP_ENV", DEFAULT_DEBUG_APP_ENV)
    DEBUG_APP_INSTANCE = env_str(env_data, "DEBUG_APP_INSTANCE", DEFAULT_DEBUG_APP_INSTANCE)

    # Debug modes.
    DEBUG_INFO_MODE = env_bool(env_data, "DEBUG_INFO_MODE", DEFAULT_DEBUG_INFO_MODE)
    DEBUG_SUCCESS_MODE = env_bool(env_data, "DEBUG_SUCCESS_MODE", DEFAULT_DEBUG_SUCCESS_MODE)
    DEBUG_SUCCESS1_MODE = env_bool(env_data, "DEBUG_SUCCESS1_MODE", DEFAULT_DEBUG_SUCCESS1_MODE)
    DEBUG_WARNING_MODE = env_bool(env_data, "DEBUG_WARNING_MODE", DEFAULT_DEBUG_WARNING_MODE)
    DEBUG_ERROR_MODE = env_bool(env_data, "DEBUG_ERROR_MODE", DEFAULT_DEBUG_ERROR_MODE)
    DEBUG_ERROR1_MODE = env_bool(env_data, "DEBUG_ERROR1_MODE", DEFAULT_DEBUG_ERROR1_MODE)
    DEBUG_CRITICAL_ERROR_MODE = env_bool(
        env_data, "DEBUG_CRITICAL_ERROR_MODE", DEFAULT_DEBUG_CRITICAL_ERROR_MODE
    )
    DEBUG_UNICODE_MODE = env_bool(env_data, "DEBUG_UNICODE_MODE", DEFAULT_DEBUG_UNICODE_MODE)
    DEBUG_RELOAD_ENV_EACH_CALL = env_bool(
        env_data, "DEBUG_RELOAD_ENV_EACH_CALL", DEFAULT_DEBUG_RELOAD_ENV_EACH_CALL
    )

    # HTTP-логирование и ротация.
    DEBUG_HTTP_LOG_MODE = env_bool(env_data, "DEBUG_HTTP_LOG_MODE", DEFAULT_DEBUG_HTTP_LOG_MODE)
    DEBUG_HTTP_CONSOLE = env_bool(env_data, "DEBUG_HTTP_CONSOLE", DEFAULT_DEBUG_HTTP_CONSOLE)

    def _int(key, default):
        try:
            return max(0, int(str(env_data.get(key, "")).strip() or default))
        except Exception:
            return default

    DEBUG_MAX_FILE_KB = _int("DEBUG_MAX_FILE_KB", DEFAULT_DEBUG_MAX_FILE_KB)
    DEBUG_MAX_FILES = _int("DEBUG_MAX_FILES", DEFAULT_DEBUG_MAX_FILES)

    # Log folder.
    BASE_LOG_DIR = resolve_log_dir(env_data)


def _reload_before_call_if_enabled() -> None:
    """Если включено — настройки перечитываются перед каждым логом."""
    if DEBUG_RELOAD_ENV_EACH_CALL:
        reload_debug_config()


def _console_write(level: str, text: str, is_error: bool = False) -> None:
    """Безопасный вывод в консоль без обычного print()."""
    try:
        stream = sys.stderr if is_error else sys.stdout
        stream.write(f"[{level}] {text}\n")
        stream.flush()

    except Exception as e:
        write_internal_error("debug_mode._console_write", str(e))


def _format_log_message(message: str, source: str | None = None) -> str:
    """
    Формирует строку обычного лога.

    DEBUG_NAME_APP и DEBUG_APP_IP сюда НЕ добавляются — они используются
    только при отправке critical-уведомлений.
    """
    parts = []

    if source:
        parts.append(f"[SOURCE:{source}]")

    parts.append(str(message))

    return " ".join(parts)


def write_log(subfolder: str, filename: str, message: str) -> str | None:
    """
    Поставить сообщение в очередь записи (фоновый поток). Возвращает путь.

    Очередь сбрасывается при остановке приложения (atexit + flush_log_writes).
    """
    try:
        _ensure_writer()
        log_path = _log_path(subfolder, filename)
        try:
            _WRITE_QUEUE.put_nowait((subfolder, filename, message))
        except queue.Full:
            # Перегрузка: пишем синхронно, чтобы не терять записи.
            _file_write_now(subfolder, filename, message)
        return log_path
    except Exception as e:
        write_internal_error("debug_mode.write_log", str(e))
        return None


def log_unicode(msg: str) -> None:
    """Пишет строку msg в stderr напрямую в UTF-8."""
    _reload_before_call_if_enabled()

    if not DEBUG_UNICODE_MODE:
        return

    try:
        sys.stderr.buffer.write(str(msg).encode("utf-8"))
        sys.stderr.buffer.write(b"\n")
        sys.stderr.flush()

    except Exception as e:
        write_internal_error("debug_mode.log_unicode", str(e))


# ==========================================================
# Debug print functions
# ==========================================================

def debug_info_print(message, source: str | None = None) -> None:
    """INFO — обычная информация."""
    _reload_before_call_if_enabled()

    if not DEBUG_INFO_MODE:
        return

    final_message = _format_log_message(str(message), source)
    _console_write("INFO", final_message)
    write_log("info_print", "info_log.log", final_message)


def debug_success_print(message, source: str | None = None) -> None:
    """SUCCESS — успешное выполнение действия."""
    _reload_before_call_if_enabled()

    if not DEBUG_SUCCESS_MODE:
        return

    final_message = _format_log_message(str(message), source)
    _console_write("SUCCESS", final_message)
    write_log("success_print", "s_log.log", final_message)


def debug_success1_print(message, source: str | None = None) -> None:
    """SUCCESS1 — успешный внутренний этап."""
    _reload_before_call_if_enabled()

    if not DEBUG_SUCCESS1_MODE:
        return

    final_message = _format_log_message(str(message), source)
    _console_write("SUCCESS1", final_message)
    write_log("success1_print", "s1_log.log", final_message)


def debug_warning_print(message, source: str | None = None) -> None:
    """WARNING — предупреждение."""
    _reload_before_call_if_enabled()

    if not DEBUG_WARNING_MODE:
        return

    final_message = _format_log_message(str(message), source)
    _console_write("WARNING", final_message)
    write_log("warning_print", "warning_log.log", final_message)


def debug_error_print(message, source: str | None = None) -> None:
    """ERROR — ошибка операции."""
    _reload_before_call_if_enabled()

    if not DEBUG_ERROR_MODE:
        return

    final_message = _format_log_message(str(message), source)
    _console_write("ERROR", final_message, is_error=True)
    write_log("error_print", "e_log.log", final_message)


def debug_error1_print(message, source: str | None = None) -> None:
    """ERROR1 — внутренняя ошибка второго уровня."""
    _reload_before_call_if_enabled()

    if not DEBUG_ERROR1_MODE:
        return

    final_message = _format_log_message(str(message), source)
    _console_write("ERROR1", final_message, is_error=True)
    write_log("error1_print", "e1_log.log", final_message)


def debug_http_log(is_error: bool, message: str) -> None:
    """
    Лог HTTP-запроса (request-лог).

    Управляется отдельным тумблером DEBUG_HTTP_LOG_MODE (не зависит от
    DEBUG_INFO_MODE) и по умолчанию НЕ дублируется в консоль, чтобы не шуметь
    поверх access-лога uvicorn.
    """
    _reload_before_call_if_enabled()

    if not DEBUG_HTTP_LOG_MODE:
        return

    final_message = _format_log_message(str(message), "http")

    if DEBUG_HTTP_CONSOLE:
        _console_write("ERROR" if is_error else "INFO", final_message, is_error=is_error)

    if is_error:
        write_log("error_print", "e_log.log", final_message)
    else:
        write_log("info_print", "info_log.log", final_message)


def critical_error_print(message: str, source: str | None = None) -> None:
    """
    CRITICAL — критическая ошибка.

    Только эта функция отправляет уведомления: Telegram / Email / Webhook.
    Уведомления шлются в отдельном потоке, чтобы сетевой I/O (до N секунд
    таймаута) не блокировал event loop.
    """
    _reload_before_call_if_enabled()

    if not DEBUG_CRITICAL_ERROR_MODE:
        return

    final_message = _format_log_message(str(message), source)

    _console_write("CRITICAL_ERROR", final_message, is_error=True)

    log_path = write_log("critical_error_print", "critical_log.log", final_message)

    try:
        if env_bool(read_env_file(), "DEBUG_CRITICAL_NOTIFY_ENABLED", False):
            threading.Thread(
                target=send_critical_notification,
                kwargs={
                    "message": str(message),
                    "app_name": DEBUG_NAME_APP,
                    "app_ip": DEBUG_APP_IP,
                    "app_env": DEBUG_APP_ENV,
                    "app_instance": DEBUG_APP_INSTANCE,
                    "source": source,
                    "log_path": log_path,
                },
                daemon=True,
            ).start()
    except Exception as e:
        write_internal_error("debug_mode.critical_error_print.notify", str(e))


# ==========================================================
# Manual runtime control
# ==========================================================

def set_debug_mode(
    info: bool = True,
    success: bool = True,
    success1: bool = True,
    warning: bool = True,
    error: bool = True,
    error1: bool = True,
    critical_error: bool = True,
    unicode_log: bool = True,
) -> None:
    """
    Временно меняет режимы в текущем процессе.

    После перезапуска или reload_debug_config() снова будут использоваться
    настройки из debug_module.env.
    """
    global DEBUG_INFO_MODE
    global DEBUG_SUCCESS_MODE
    global DEBUG_SUCCESS1_MODE
    global DEBUG_WARNING_MODE
    global DEBUG_ERROR_MODE
    global DEBUG_ERROR1_MODE
    global DEBUG_CRITICAL_ERROR_MODE
    global DEBUG_UNICODE_MODE

    DEBUG_INFO_MODE = info
    DEBUG_SUCCESS_MODE = success
    DEBUG_SUCCESS1_MODE = success1
    DEBUG_WARNING_MODE = warning
    DEBUG_ERROR_MODE = error
    DEBUG_ERROR1_MODE = error1
    DEBUG_CRITICAL_ERROR_MODE = critical_error
    DEBUG_UNICODE_MODE = unicode_log


# ==========================================================
# Настройки для админки («Настройки → Логи»)
# ==========================================================

def get_debug_settings() -> dict:
    """Текущие настройки debug-модуля для формы в админке."""
    return {
        "DEBUG_NAME_APP": DEBUG_NAME_APP,
        "DEBUG_APP_IP": DEBUG_APP_IP,
        "DEBUG_APP_ENV": DEBUG_APP_ENV,
        "DEBUG_APP_INSTANCE": DEBUG_APP_INSTANCE,
        "DEBUG_INFO_MODE": DEBUG_INFO_MODE,
        "DEBUG_SUCCESS_MODE": DEBUG_SUCCESS_MODE,
        "DEBUG_SUCCESS1_MODE": DEBUG_SUCCESS1_MODE,
        "DEBUG_WARNING_MODE": DEBUG_WARNING_MODE,
        "DEBUG_ERROR_MODE": DEBUG_ERROR_MODE,
        "DEBUG_ERROR1_MODE": DEBUG_ERROR1_MODE,
        "DEBUG_CRITICAL_ERROR_MODE": DEBUG_CRITICAL_ERROR_MODE,
        "DEBUG_UNICODE_MODE": DEBUG_UNICODE_MODE,
        "DEBUG_RELOAD_ENV_EACH_CALL": DEBUG_RELOAD_ENV_EACH_CALL,
        "DEBUG_HTTP_LOG_MODE": DEBUG_HTTP_LOG_MODE,
        "DEBUG_HTTP_CONSOLE": DEBUG_HTTP_CONSOLE,
        "DEBUG_MAX_FILE_KB": DEBUG_MAX_FILE_KB,
        "DEBUG_MAX_FILES": DEBUG_MAX_FILES,
        "DEBUG_LOG_DIR": str(BASE_LOG_DIR),
        "DEBUG_CRITICAL_NOTIFY_ENABLED": env_bool(
            read_env_file(), "DEBUG_CRITICAL_NOTIFY_ENABLED", False
        ),
        "DEBUG_CRITICAL_NOTIFY_CHANNEL": env_str(
            read_env_file(), "DEBUG_CRITICAL_NOTIFY_CHANNEL", "none"
        ),
    }


def apply_debug_settings(updates: dict) -> None:
    """
    Применить настройки: записать в debug_module.env и перезагрузить модуль.

    Принимает только белые ключи — всё остальное игнорируется.
    """
    allowed = {
        "DEBUG_INFO_MODE", "DEBUG_SUCCESS_MODE", "DEBUG_SUCCESS1_MODE",
        "DEBUG_WARNING_MODE", "DEBUG_ERROR_MODE", "DEBUG_ERROR1_MODE",
        "DEBUG_CRITICAL_ERROR_MODE", "DEBUG_UNICODE_MODE",
        "DEBUG_RELOAD_ENV_EACH_CALL", "DEBUG_HTTP_LOG_MODE",
        "DEBUG_HTTP_CONSOLE", "DEBUG_MAX_FILE_KB", "DEBUG_MAX_FILES",
        "DEBUG_NAME_APP", "DEBUG_APP_IP", "DEBUG_APP_ENV",
        "DEBUG_APP_INSTANCE", "DEBUG_CRITICAL_NOTIFY_ENABLED",
        "DEBUG_CRITICAL_NOTIFY_CHANNEL",
        "DEBUG_AUTO_CLEAN_ENABLED", "DEBUG_LOG_RETENTION",
    }
    clean = {}
    for key, value in updates.items():
        if key not in allowed:
            continue
        raw = str(value).strip().lower()
        if raw in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            clean[key] = "True" if raw in {"true", "1", "yes", "on"} else "False"
        else:
            clean[key] = str(value).strip()

    if not clean:
        return

    from app.on_off_debug.env_tools import update_env_file

    update_env_file(clean)
    reload_debug_config()


def clear_all_logs() -> tuple[int, int]:
    """
    Полностью удаляет папку логов. Возвращает (удалено_файлов, освобождено_байт).
    """
    import shutil

    removed_files = 0
    freed_bytes = 0

    if os.path.exists(BASE_LOG_DIR):
        for root, _, filenames in os.walk(BASE_LOG_DIR):
            for fname in filenames:
                fpath = os.path.join(root, fname)
                try:
                    freed_bytes += os.path.getsize(fpath)
                    os.remove(fpath)
                    removed_files += 1
                except Exception as e:
                    write_internal_error("debug_mode.clear_all_logs", str(e))
        # Пустые подпапки дат можно оставить — они лёгкие, но уберём мусор.
        try:
            shutil.rmtree(BASE_LOG_DIR, ignore_errors=True)
        except Exception as e:
            write_internal_error("debug_mode.clear_all_logs.rmtree", str(e))

    return removed_files, freed_bytes


# ==========================================================
# Auto load config
# ==========================================================

reload_debug_config()
clean_on_start_if_enabled()
