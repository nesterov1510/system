"""Контроль запуска приложения по IP/порту (порт из start_ip_controll архива).

Модуль читает ``start_ip_controll/ip_controll.env`` (или системные переменные
окружения — они имеют приоритет), определяет локальные IP-адреса сервера и
возвращает готовые ``host``/``port`` для запуска uvicorn::

    python -m start_ip_controll

Логика полностью повторяет исходный Flask-модуль, но вместо ``on_off_debug``
используется стандартный ``logging`` и нет жёсткой привязки к Flask.

Настройки (ip_controll.env):
  MAIN_LOCAL_HOST=True              — слушать только 127.0.0.1
  MAIN_NA_VCEH_IP_START=True        — слушать 0.0.0.0 (все интерфейсы)
  MAIN_RAZRESHENNIYE_IP_PROVERKA=False — проверять, что IP сервера в белом списке
  MAIN_KAKIYE_IP_RAZRESHEN_DLYA_START=192.168.66.1, 192.168.66.0/24
  MAIN_START_PORT=8085
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("start_ip_controll")

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = Path(os.environ.get("IP_CONTROLL_ENV", BASE_DIR / "ip_controll.env"))

LOG_SOURCE = "start_ip_controll.ip_controll"

# Порт по умолчанию — боевой порт MSB (в исходнике был 5001 под Flask).
DEFAULT_PORT = 8085
LOCAL_HOST = "127.0.0.1"
ALL_INTERFACES_HOST = "0.0.0.0"


@dataclass(frozen=True)
class ServerStartConfig:
    """Готовая конфигурация для запуска uvicorn (host/port)."""

    host: str
    port: int
    local_host_enabled: bool
    all_ip_start_enabled: bool
    allowed_ip_check_enabled: bool
    allowed_start_rules: Tuple[str, ...]
    detected_local_ips: Tuple[str, ...]


# Совместимое старое имя (в оригинале это была FlaskStartConfig).
FlaskStartConfig = ServerStartConfig


# ==========================================================
# ENV reader
# ==========================================================

def read_ip_controll_env(env_path: Optional[str | Path] = None) -> Dict[str, str]:
    """Читает ip_controll.env без сторонних библиотек."""
    path = Path(env_path) if env_path else ENV_PATH
    data: Dict[str, str] = {}

    if not path.exists():
        log.warning("Файл ip_controll.env не найден: %s. Будут использованы default-настройки.", path)
        return data

    try:
        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not key:
                    log.warning("Пропущена строка ip_controll.env без ключа. line=%d", line_number)
                    continue
                data[key] = value
        log.info("Файл ip_controll.env успешно прочитан: %s", path)
    except Exception as e:  # pragma: no cover - защита от битого файла
        log.error("Ошибка чтения ip_controll.env: %s", e)
        return {}

    return data


# ==========================================================
# Small helpers
# ==========================================================

def _env_value(data: Dict[str, str], key: str, default: str) -> str:
    value = os.environ.get(key, data.get(key))
    if value is None:
        return default
    value = str(value).strip()
    return value if value else default


def _env_bool(data: Dict[str, str], key: str, default: bool = False) -> bool:
    value = os.environ.get(key, data.get(key))
    if value is None:
        return default
    value = str(value).strip().lower()
    true_values = {"true", "1", "yes", "y", "on", "enable", "enabled", "да", "истина"}
    false_values = {"false", "0", "no", "n", "off", "disable", "disabled", "нет", "ложь"}
    if value in true_values:
        return True
    if value in false_values:
        return False
    message = f"Некорректное bool-значение для {key}: {value}."
    log.critical(message)
    raise RuntimeError(message)


def _env_int(data: Dict[str, str], key: str, default: int) -> int:
    value = os.environ.get(key, data.get(key))
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except Exception:
        message = f"Некорректное int-значение для {key}: {value}."
        log.critical(message)
        raise RuntimeError(message)


def _csv_list(value: str) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _unique_sorted(values: Sequence[str]) -> Tuple[str, ...]:
    return tuple(sorted({str(item).strip() for item in values if str(item).strip()}))


def _fail_start(message: str) -> None:
    """Останавливает запуск приложения при неправильной start-конфигурации."""
    log.critical(message)
    raise RuntimeError(message)


# ==========================================================
# IP helpers
# ==========================================================

def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(str(value).strip())
        return True
    except Exception:
        return False


def _is_network_rule(value: str) -> bool:
    return "/" in str(value or "")


def _is_valid_ip_or_network_rule(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    try:
        if _is_network_rule(value):
            ipaddress.ip_network(value, strict=False)
        else:
            ipaddress.ip_address(value)
        return True
    except Exception:
        return False


def _ip_matches_rule(ip_value: str, rule: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(str(ip_value).strip())
        rule = str(rule or "").strip()
        if not rule:
            return False
        if _is_network_rule(rule):
            return ip_obj in ipaddress.ip_network(rule, strict=False)
        return ip_obj == ipaddress.ip_address(rule)
    except Exception:
        return False


def _ip_matches_any_rule(ip_value: str, rules: Sequence[str]) -> bool:
    return any(_ip_matches_rule(ip_value, rule) for rule in rules)


def _get_detected_local_ips() -> Tuple[str, ...]:
    """IP-адреса текущей машины (без внешних библиотек)."""
    found: List[str] = [LOCAL_HOST]

    # 1) UDP route detection (интернет не нужен — сокет лишь выбирает интерфейс)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip:
            found.append(ip)
    except Exception as e:
        log.warning("Не удалось определить IP через UDP route detection: %s", e)

    # 2) Через hostname
    try:
        hostname = socket.gethostname()
        hostname_ip = socket.gethostbyname(hostname)
        if hostname_ip:
            found.append(hostname_ip)
    except Exception as e:
        log.warning("Не удалось определить IP через hostname: %s", e)

    # 3) Все адреса hostname через getaddrinfo
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None):
            ip = item[4][0]
            if ip:
                found.append(ip)
    except Exception as e:
        log.warning("Не удалось получить список IP через getaddrinfo: %s", e)

    cleaned = []
    for ip in found:
        ip = str(ip).split("%", 1)[0].strip()
        if _is_ip_address(ip):
            cleaned.append(ip)

    return _unique_sorted(cleaned)


def _validate_allowed_rules(raw_rules: Sequence[str]) -> Tuple[str, ...]:
    valid_rules: List[str] = []
    for rule in raw_rules:
        if _is_valid_ip_or_network_rule(rule):
            valid_rules.append(rule)
            continue
        _fail_start(f"MAIN_KAKIYE_IP_RAZRESHEN_DLYA_START содержит некорректное правило: {rule}")
    return tuple(valid_rules)


def _detect_allowed_local_ips(detected_local_ips: Sequence[str],
                              allowed_rules: Sequence[str]) -> Tuple[str, ...]:
    if not allowed_rules:
        return tuple(detected_local_ips)
    matched = [ip for ip in detected_local_ips if _ip_matches_any_rule(ip, allowed_rules)]
    return _unique_sorted(matched)


def _choose_specific_host_from_allowed_ips(allowed_local_ips: Sequence[str]) -> str:
    """Конкретный IP для bind, если запуск на всех IP выключен (не loopback)."""
    for ip in allowed_local_ips:
        if ip not in {"127.0.0.1", "::1"}:
            return ip
    return LOCAL_HOST


# ==========================================================
# Public loader
# ==========================================================

def get_server_start_config() -> ServerStartConfig:
    """Готовые host/port для запуска uvicorn.

    Приоритет настроек: 1) переменные окружения; 2) ip_controll.env; 3) default.
    """
    data = read_ip_controll_env()

    main_local_host = _env_bool(data, "MAIN_LOCAL_HOST", default=True)
    main_na_vceh_ip_start = _env_bool(data, "MAIN_NA_VCEH_IP_START", default=False)
    main_allowed_ip_check = _env_bool(data, "MAIN_RAZRESHENNIYE_IP_PROVERKA", default=False)

    raw_allowed_rules = _csv_list(
        _env_value(data, "MAIN_KAKIYE_IP_RAZRESHEN_DLYA_START", "")
    )

    port = _env_int(data, "MAIN_START_PORT", DEFAULT_PORT)
    if port < 1 or port > 65535:
        _fail_start(f"MAIN_START_PORT={port} вне системного диапазона 1-65535.")

    detected_local_ips = _get_detected_local_ips()

    if main_allowed_ip_check:
        allowed_rules = _validate_allowed_rules(raw_allowed_rules)
        allowed_local_ips = _detect_allowed_local_ips(detected_local_ips, allowed_rules)
    else:
        allowed_rules = tuple()
        allowed_local_ips = tuple(detected_local_ips)

    log.info(
        "Проверка start config: MAIN_LOCAL_HOST=%s, MAIN_NA_VCEH_IP_START=%s, "
        "MAIN_RAZRESHENNIYE_IP_PROVERKA=%s, MAIN_START_PORT=%s",
        main_local_host, main_na_vceh_ip_start, main_allowed_ip_check, port,
    )
    log.info("Обнаруженные IP сервера: %s", list(detected_local_ips))

    if main_allowed_ip_check:
        if not allowed_rules:
            _fail_start(
                "MAIN_RAZRESHENNIYE_IP_PROVERKA=True, но "
                "MAIN_KAKIYE_IP_RAZRESHEN_DLYA_START пустой. "
                "Укажи IP/сеть или выключи проверку: MAIN_RAZRESHENNIYE_IP_PROVERKA=False."
            )
        log.info("Проверка разрешённых IP/сетей включена. Правила: %s", list(allowed_rules))
        if not allowed_local_ips:
            _fail_start(
                "Ни один IP текущего сервера не входит в "
                f"MAIN_KAKIYE_IP_RAZRESHEN_DLYA_START={list(allowed_rules)}. "
                f"Обнаруженные IP: {list(detected_local_ips)}"
            )
    else:
        log.warning(
            "MAIN_RAZRESHENNIYE_IP_PROVERKA=False: проверка белого списка IP выключена."
        )

    # --- Выбор host ---
    if main_na_vceh_ip_start:
        host = ALL_INTERFACES_HOST
        log.warning(
            "MAIN_NA_VCEH_IP_START=True: сервер слушает все интерфейсы (0.0.0.0). "
            "Открывать через 127.0.0.1 или реальный IP сервера, не через 0.0.0.0."
        )
    elif main_local_host:
        host = LOCAL_HOST
        log.info("MAIN_LOCAL_HOST=True: сервер доступен только локально (127.0.0.1).")
    elif allowed_local_ips:
        host = _choose_specific_host_from_allowed_ips(allowed_local_ips)
        log.info("Выбран конкретный разрешённый IP для запуска: %s", host)
    else:
        _fail_start(
            "Не удалось выбрать host: MAIN_NA_VCEH_IP_START=False, MAIN_LOCAL_HOST=False, "
            "и нет подходящего разрешённого IP."
        )

    log.info(
        "Start config готов: host=%s, port=%s, MAIN_LOCAL_HOST=%s, "
        "MAIN_NA_VCEH_IP_START=%s, MAIN_RAZRESHENNIYE_IP_PROVERKA=%s",
        host, port, main_local_host, main_na_vceh_ip_start, main_allowed_ip_check,
    )

    return ServerStartConfig(
        host=host,
        port=port,
        local_host_enabled=main_local_host,
        all_ip_start_enabled=main_na_vceh_ip_start,
        allowed_ip_check_enabled=main_allowed_ip_check,
        allowed_start_rules=allowed_rules,
        detected_local_ips=detected_local_ips,
    )


# Совместимое старое имя функции.
get_flask_start_config = get_server_start_config
