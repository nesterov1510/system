"""Запуск uvicorn с host/port из start_ip_controll.

Использование:
    python -m start_ip_controll

Берёт ``host``/``port`` из ``ip_controll.env`` (или переменных окружения) и
поднимает приложение ``app.main:app``. Файл env можно переопределить:
    IP_CONTROLL_ENV=/path/to/ip_controll.env python -m start_ip_controll
"""
from __future__ import annotations

import logging
import socket
import sys

import uvicorn

from .ip_controll import get_server_start_config

# Пакеты, без которых приложение не стартует (имя для импорта -> имя в pip).
_REQUIRED = {
    "pydantic_settings": "pydantic-settings",
    "pydantic": "pydantic",
    "fastapi": "fastapi",
    "sqlalchemy": "sqlalchemy",
    "jinja2": "jinja2",
    "reportlab": "reportlab",
    "qrcode": "qrcode[pil]",
    "jwt": "PyJWT",
    "bcrypt": "bcrypt",
    "multipart": "python-multipart",
    "httpx": "httpx",
    "requests": "requests",
    "asyncpg": "asyncpg",
    "aiosqlite": "aiosqlite",
}


def _check_dependencies() -> None:
    """Дать понятную ошибку, если в текущем интерпретаторе нет зависимостей."""
    missing = []
    for module, pip_name in _REQUIRED.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)
    if missing:
        logging.getLogger("start_ip_controll").error(
            "В текущем интерпретаторе (%s) не установлены зависимости: %s\n"
            "Установите их ТЕМ ЖЕ интерпретатором, которым запускаете сервис:\n"
            "  %s -m pip install -r requirements.txt\n"
            "Либо (если пакеты кладёте в каталог пользователя):\n"
            "  %s -m pip install --user -r requirements.txt\n"
            "После установки перезапустите сервис: systemctl restart msb-api",
            sys.executable,
            ", ".join(sorted(set(missing))),
            sys.executable,
            sys.executable,
        )
        raise SystemExit(1)


def _check_port_free(host: str, port: int) -> None:
    """Быстро падаем с понятной ошибкой, если host:port уже занят.

    Без этого uvicorn сначала выполняет startup приложения (создание схемы,
    миграции, seed, фоновые задачи) и только потом падает на bind — шумно и
    медленно. Проверка ловит занятый порт до запуска.
    """
    # Для 0.0.0.0 проверяем «любой адрес» (bind на 0.0.0.0 конфликтует с любым
    # слушателем на этом порту); для конкретного IP — именно его.
    probe_host = "0.0.0.0" if host in ("0.0.0.0", "::") else host
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((probe_host, port))
    except OSError:
        logging.getLogger("start_ip_controll").error(
            "\n"
            "============================================================\n"
            "Порт %s на %s ЗАНЯТ — другой процесс уже слушает его.\n"
            "Скорее всего, это старый экземпляр сервера, не остановленный\n"
            "при обновлении. Найдите и остановите его:\n"
            "  sudo ss -ltnp 'sport = :%s'        # кто слушает порт\n"
            "  sudo systemctl stop msb-api         # если это старый сервис\n"
            "  sudo fuser -k %s/tcp               # ИЛИ убить процесс на порту\n"
            "После этого снова запустите сервис:\n"
            "  sudo systemctl start msb-api\n"
            "============================================================\n",
            port, host, port, port,
        )
        raise SystemExit(1)
    finally:
        sock.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = get_server_start_config()
    _check_dependencies()
    _check_port_free(cfg.host, cfg.port)
    # proxy_headers=False: uvicorn НЕ подменяет IP клиента заголовком
    # X-Forwarded-For. Так запросы приходят с настоящим IP пира, и его нельзя
    # подделать заголовком (важно для IP-контроля доступа). Если сервис
    # поставите за обратный прокси (nginx), включите в /admin/settings →
    # IP-контроль чекбокс «доверять X-Forwarded-For» — тогда заголовок будет
    # учитываться на уровне приложения (и прокси должен его перезаписывать).
    uvicorn.run(
        "app.main:app",
        host=cfg.host,
        port=cfg.port,
        workers=1,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
