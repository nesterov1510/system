# ruff: noqa: BLE001  -- порт из архива: широкий except и локальное время — намеренно
# on_off_debug/env_tools.py
import os
import re
import socket

from app.on_off_debug.internal_logger import write_internal_error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, "debug_module.env")


def read_env_file(env_path: str | None = None) -> dict:
    """Читает debug_module.env без сторонних библиотек."""
    if env_path is None:
        env_path = ENV_PATH

    data = {}

    if not os.path.exists(env_path):
        return data

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                data[key.strip()] = value.strip().strip('"').strip("'")

    except Exception as e:
        write_internal_error("env_tools.read_env_file", str(e))

    return data


def env_bool(data: dict, key: str, default: bool = True) -> bool:
    """Читает bool из env."""
    value = data.get(key)

    if value is None:
        return default

    value = str(value).strip().lower()

    true_values = {"true", "1", "yes", "y", "on", "enable", "enabled"}
    false_values = {"false", "0", "no", "n", "off", "disable", "disabled"}

    if value in true_values:
        return True

    if value in false_values:
        return False

    return default


def env_int(data: dict, key: str, default: int, min_value: int = 1) -> int:
    """Читает int из env."""
    value = data.get(key)

    if value is None:
        return default

    try:
        result = int(str(value).strip())
        return result if result >= min_value else default
    except Exception:
        return default


def env_str(data: dict, key: str, default: str = "") -> str:
    """Читает строку из env."""
    value = data.get(key)

    if value is None:
        return default

    value = str(value).strip()
    return value if value else default


def safe_folder_name(value: str, default: str = "unknown") -> str:
    """Делает безопасное имя папки."""
    value = str(value or "").strip()

    if not value:
        return default

    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)
    value = value.strip("._-")

    return value if value else default


def resolve_log_dir(env_data: dict, default_log_dir: str = "log_folder") -> str:
    """
    Определяет базовую папку логов из DEBUG_LOG_DIR.

    DEBUG_LOG_DIR=log_folder -> on_off_debug/log_folder
    DEBUG_LOG_DIR=/var/log/project -> /var/log/project
    """
    custom_log_dir = env_data.get("DEBUG_LOG_DIR", default_log_dir)

    if not custom_log_dir:
        return os.path.join(BASE_DIR, default_log_dir)

    custom_log_dir = str(custom_log_dir).strip()

    if os.path.isabs(custom_log_dir):
        return custom_log_dir

    return os.path.join(BASE_DIR, custom_log_dir)


def get_auto_ip() -> str:
    """
    Пытается определить локальный IP сервера/машины.
    Это не публичный IP из интернета.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()

        if ip:
            return ip

    except Exception as e:
        write_internal_error("env_tools.get_auto_ip.udp", str(e))

    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)

        if ip:
            return ip

    except Exception as e:
        write_internal_error("env_tools.get_auto_ip.hostname", str(e))

    return "unknown"


def update_env_file(updates: dict, env_path: str | None = None) -> None:
    """
    Обновить значения в debug_module.env, сохранив комментарии и порядок строк.

    Ключи, которых ещё нет, дописываются в конец. Используется страницей
    «Настройки → Логи», чтобы менять параметры debug-модуля без правки файла
    руками.
    """
    if env_path is None:
        env_path = ENV_PATH

    if not updates:
        return

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        lines = []

    updated: set = set()
    out: list = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}\n")
            updated.add(key)
        else:
            out.append(line)

    for key, value in updates.items():
        if key not in updated:
            out.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(out)

