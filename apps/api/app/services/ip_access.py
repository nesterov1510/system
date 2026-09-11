"""Фильтр доступа к веб-интерфейсу по IP клиента (управляется из админки).

Настройки хранятся в таблице settings (ключ ``ip_control``) и редактируются
администратором на странице /admin/settings. Поддерживаются три режима:

* ``off``       — фильтр выключен, доступ открыт всем;
* ``whitelist`` — разрешены только перечисленные IP/сети (белый список);
* ``blacklist`` — запрещены перечисленные IP/сети (чёрный список).

Правила — это отдельные IP (``192.168.8.81``) или сети CIDR
(``192.168.8.0/24``). Локальные адреса (loopback) и приватные сети сервера
можно не блокировать — loopback всегда разрешён, чтобы админ не отрезал сам
себя.
"""
from __future__ import annotations

import asyncio
import ipaddress
import time
from typing import Iterable

# Сколько секунд кэшируем загруженные правила, чтобы не ходить в БД на каждый
# HTTP-запрос. После сохранения настроек кэш сбрасывается (invalidate).
_CACHE_TTL_SEC = 30.0

_cache: dict = {"rules": None, "ts": 0.0}


# ---------------------------------------------------------------------------
# Чистые функции сопоставления IP/правил (легко тестируются без БД).
# ---------------------------------------------------------------------------

def is_valid_rule(rule: str) -> bool:
    """True, если строка — корректный IP или CIDR-сеть."""
    rule = (rule or "").strip()
    if not rule:
        return False
    try:
        if "/" in rule:
            ipaddress.ip_network(rule, strict=False)
        else:
            ipaddress.ip_address(rule)
        return True
    except ValueError:
        return False


def normalize_rules(rules: Iterable[str]) -> list[str]:
    """Оставить только корректные правила, убрать дубли и пробелы."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in rules or []:
        rule = str(raw).strip()
        if not rule or not is_valid_rule(rule):
            continue
        # Нормализуем сеть (192.168.8.10/24 -> 192.168.8.0/24) для сравнения.
        if "/" in rule:
            rule = str(ipaddress.ip_network(rule, strict=False))
        if rule not in seen:
            seen.add(rule)
            out.append(rule)
    return out


def _ip_in_rules(ip: str, rules: Iterable[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0].strip())
    except ValueError:
        return False
    for rule in rules:
        try:
            if "/" in rule:
                if addr in ipaddress.ip_network(rule, strict=False):
                    return True
            elif addr == ipaddress.ip_address(rule):
                return True
        except ValueError:
            continue
    return False


def is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address((ip or "").split("%", 1)[0].strip()).is_loopback
    except ValueError:
        return False


def client_ip_allowed(ip: str, mode: str, whitelist: list[str], blacklist: list[str]) -> bool:
    """Главное правило фильтрации.

    Loopback всегда разрешён (защита от самоблокировки). Дальше — по режиму.
    """
    if not ip or is_loopback(ip):
        return True
    if mode == "blacklist":
        return not _ip_in_rules(ip, blacklist)
    if mode == "whitelist":
        return _ip_in_rules(ip, whitelist)
    return True  # off


def extract_client_ip(headers, peer_host: str | None, trust_proxy: bool = False) -> str:
    """Определить IP клиента.

    По умолчанию (trust_proxy=False) берём адрес прямого пира (scope client) —
    это надёжно: клиент не может его подделать. Заголовок X-Forwarded-For
    доверяем ТОЛЬКО если приложение стоит за обратным прокси (nginx), который
    перезаписывает этот заголовок — иначе заблокированный клиент мог бы прислать
    X-Forwarded-For: 127.0.0.1 и обойти фильтр.
    """
    if trust_proxy:
        xff = ""
        if hasattr(headers, "get"):
            xff = headers.get("x-forwarded-for", "") or ""
        if xff:
            # "client, proxy1, proxy2" — клиент самый первый.
            return xff.split(",")[0].strip()
    return (peer_host or "").strip()


# ---------------------------------------------------------------------------
# Кэш загруженных правил (чтобы не дёргать БД на каждый запрос).
# ---------------------------------------------------------------------------

def invalidate_cache() -> None:
    _cache["rules"] = None
    _cache["ts"] = 0.0


async def get_rules_cached(db_factory) -> dict:
    """Вернуть актуальные правила ip_control с коротким кэшем.

    db_factory — async-фабрика сессий (async_session_factory).
    """
    now = time.time()
    if _cache["rules"] is not None and (now - _cache["ts"]) < _CACHE_TTL_SEC:
        return _cache["rules"]

    rules = {"mode": "off", "whitelist": [], "blacklist": [], "trust_proxy": False}
    db = db_factory()
    try:
        from app.services.settings import get_ip_control  # локальный импорт
        saved = await get_ip_control(db)
        rules["mode"] = saved.get("mode", "off")
        rules["whitelist"] = normalize_rules(saved.get("whitelist", []))
        rules["blacklist"] = normalize_rules(saved.get("blacklist", []))
        rules["trust_proxy"] = bool(saved.get("trust_proxy"))
    except Exception:
        # При ошибке чтения настроек не блокируем сервис.
        pass
    finally:
        await db.close()

    _cache["rules"] = rules
    _cache["ts"] = now
    return rules


# ---------------------------------------------------------------------------
# Журнал попыток подключения (вкладка «IP-контроль» в админке).
#
# Запись идёт в фоне через одну asyncio-очередь и одного писателя, чтобы не
# замедлять запросы и не ронять их при сбоях БД. При остановке приложения
# остаток очереди дописывается в lifespan (см. flush_log).
# ---------------------------------------------------------------------------

_LOG_QUEUE: asyncio.Queue | None = None
_LOG_TASK: asyncio.Task | None = None
_LOG_QUEUE_MAX = 5000


def record_attempt(
    ip: str,
    allowed: bool,
    mode: str,
    path: str,
    user_agent: str | None = None,
) -> None:
    """Поставить попытку подключения в очередь записи журнала.

    Никогда не бросает исключений: если event loop недоступен или очередь
    переполнена — просто пропускаем (журнал не критичен для работы).
    """
    if not ip:
        return
    global _LOG_QUEUE, _LOG_TASK
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # вне event loop (например, в тестах) — не пишем

    if _LOG_QUEUE is None:
        _LOG_QUEUE = asyncio.Queue(maxsize=_LOG_QUEUE_MAX)
    if _LOG_TASK is None or _LOG_TASK.done():
        _LOG_TASK = loop.create_task(_log_writer_loop())

    try:
        _LOG_QUEUE.put_nowait(
            {
                "ip": ip[:64],
                "allowed": bool(allowed),
                "mode": (mode or "off")[:16],
                "path": (path or "")[:255],
                "user_agent": (user_agent or "")[:512],
            }
        )
    except asyncio.QueueFull:
        pass


async def _log_writer_loop() -> None:
    """Фоновый писатель: собирает пачку попыток и складывает в БД."""
    while True:
        try:
            batch = [await _LOG_QUEUE.get()]
        except asyncio.CancelledError:
            break
        while True:
            try:
                batch.append(_LOG_QUEUE.get_nowait())
            except asyncio.QueueEmpty:
                break
        try:
            await _persist_attempts(batch)
        except Exception:  # noqa: BLE001 — сбой журнала не должен влиять на API
            pass


async def _persist_attempts(batch: list[dict]) -> None:
    """Сложить пачку попыток в таблицу ip_access_log."""
    if not batch:
        return
    from app.db.models import IpAccessLog
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        for item in batch:
            db.add(IpAccessLog(**item))
        await db.commit()


async def flush_log() -> None:
    """Дописать остаток очереди журнала (вызывается при остановке приложения)."""
    global _LOG_QUEUE
    if _LOG_QUEUE is None:
        return
    batch: list[dict] = []
    while True:
        try:
            batch.append(_LOG_QUEUE.get_nowait())
        except asyncio.QueueEmpty:
            break
    if batch:
        try:
            await _persist_attempts(batch)
        except Exception:  # noqa: BLE001
            pass


async def get_attempts_summary(db, limit: int = 200) -> list[dict]:
    """Агрегация попыток по IP: всего, заблокировано, последняя попытка."""
    from sqlalchemy import case, func, select

    from app.db.models import IpAccessLog

    rows = (
        await db.execute(
            select(
                IpAccessLog.ip,
                func.count(IpAccessLog.id).label("total"),
                func.sum(case((IpAccessLog.allowed.is_(False), 1), else_=0)).label("blocked"),
                func.max(IpAccessLog.created_at).label("last_seen"),
            )
            .group_by(IpAccessLog.ip)
            .order_by(func.max(IpAccessLog.created_at).desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "ip": ip,
            "total": int(total or 0),
            "blocked": int(blocked or 0),
            "last_seen": last_seen,
        }
        for ip, total, blocked, last_seen in rows
    ]


async def get_recent_attempts(db, limit: int = 50) -> list[dict]:
    """Последние попытки подключения (свежие сверху)."""
    from sqlalchemy import select

    from app.db.models import IpAccessLog

    rows = (
        (
            await db.execute(
                select(IpAccessLog).order_by(IpAccessLog.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "ip": r.ip,
            "allowed": bool(r.allowed),
            "mode": r.mode,
            "path": r.path,
            "created_at": r.created_at,
        }
        for r in rows
    ]


async def clear_attempts(db) -> int:
    """Очистить весь журнал попыток. Возвращает число удалённых строк."""
    from sqlalchemy import delete

    from app.db.models import IpAccessLog

    res = await db.execute(delete(IpAccessLog))
    await db.commit()
    return res.rowcount or 0
