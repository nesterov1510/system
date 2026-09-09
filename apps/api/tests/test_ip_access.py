"""Тесты IP-контроля доступа (app/services/ip_access.py).

Проверяем чистые функции сопоставления правил и кэш загрузки настроек —
без поднятия БД (фейковая async-фабрика сессий).
"""
from __future__ import annotations

import pytest

from app.services import ip_access


# ---------------------------------------------------------------------------
# is_valid_rule / normalize_rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rule,expected",
    [
        ("192.168.8.81", True),
        ("10.0.0.5", True),
        ("192.168.8.0/24", True),
        ("192.168.8.10/24", True),  # host-биты — валидно, сеть нормализуется
        ("0.0.0.0/0", True),
        ("::1", True),
        ("fe80::/10", True),
        ("", False),
        ("   ", False),
        ("banana", False),
        ("999.999.1.1", False),
        ("192.168.8.0/33", False),
    ],
)
def test_is_valid_rule(rule, expected):
    assert ip_access.is_valid_rule(rule) is expected


def test_normalize_rules_dedup_and_network():
    out = ip_access.normalize_rules(
        ["192.168.8.10/24", " 8.8.8.8 ", "bad-rule", "8.8.8.8", "", None]
    )
    assert out == ["192.168.8.0/24", "8.8.8.8"]


def test_normalize_rules_empty():
    assert ip_access.normalize_rules([]) == []
    assert ip_access.normalize_rules(None) == []


# ---------------------------------------------------------------------------
# _ip_in_rules
# ---------------------------------------------------------------------------

def test_ip_in_rules_exact_and_cidr():
    rules = ["192.168.8.81", "10.0.0.0/8"]
    assert ip_access._ip_in_rules("192.168.8.81", rules) is True
    assert ip_access._ip_in_rules("10.200.3.7", rules) is True
    assert ip_access._ip_in_rules("172.16.0.1", rules) is False


def test_ip_in_rules_bad_input():
    assert ip_access._ip_in_rules("banana", ["10.0.0.0/8"]) is False
    assert ip_access._ip_in_rules("10.0.0.1", ["banana"]) is False
    # IPv6 zone index не ломает матчинг
    assert ip_access._ip_in_rules("fe80::1%eth0", ["fe80::/10"]) is True


# ---------------------------------------------------------------------------
# is_loopback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ip,expected",
    [("127.0.0.1", True), ("::1", True), ("192.168.8.81", False), ("8.8.8.8", False), ("", False)],
)
def test_is_loopback(ip, expected):
    assert ip_access.is_loopback(ip) is expected


# ---------------------------------------------------------------------------
# client_ip_allowed (главное правило)
# ---------------------------------------------------------------------------

def test_mode_off_allows_everyone():
    assert ip_access.client_ip_allowed("8.8.8.8", "off", [], []) is True
    assert ip_access.client_ip_allowed("203.0.113.9", "off", [], ["203.0.113.0/24"]) is True


def test_blacklist_mode():
    black = ["203.0.113.0/24", "198.51.100.7"]
    assert ip_access.client_ip_allowed("203.0.113.9", "blacklist", [], black) is False
    assert ip_access.client_ip_allowed("198.51.100.7", "blacklist", [], black) is False
    assert ip_access.client_ip_allowed("8.8.8.8", "blacklist", [], black) is True


def test_whitelist_mode():
    white = ["192.168.8.0/24", "10.0.0.5"]
    assert ip_access.client_ip_allowed("192.168.8.55", "whitelist", white, []) is True
    assert ip_access.client_ip_allowed("10.0.0.5", "whitelist", white, []) is True
    assert ip_access.client_ip_allowed("8.8.8.8", "whitelist", white, []) is False


def test_loopback_always_allowed():
    # Даже «запретить всё» чёрным списком не должен отрезать localhost.
    assert ip_access.client_ip_allowed("127.0.0.1", "blacklist", [], ["0.0.0.0/0"]) is True
    assert ip_access.client_ip_allowed("::1", "blacklist", [], ["0.0.0.0/0"]) is True
    # И даже пустой белый список разрешает loopback (админ не блокирует себя).
    assert ip_access.client_ip_allowed("127.0.0.1", "whitelist", [], []) is True


def test_empty_ip_is_allowed():
    assert ip_access.client_ip_allowed("", "whitelist", [], []) is True


# ---------------------------------------------------------------------------
# extract_client_ip (X-Forwarded-For доверяем только за прокси)
# ---------------------------------------------------------------------------

class _Headers(dict):
    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)


def test_extract_uses_peer_without_proxy():
    h = _Headers({"x-forwarded-for": "203.0.113.9, 10.0.0.1"})
    # Без trust_proxy заголовок игнорируется — берём реальный пир.
    assert ip_access.extract_client_ip(h, "192.168.8.81") == "192.168.8.81"


def test_extract_uses_xff_with_proxy():
    h = _Headers({"x-forwarded-for": "203.0.113.9, 10.0.0.1"})
    assert ip_access.extract_client_ip(h, "192.168.8.81", trust_proxy=True) == "203.0.113.9"


def test_extract_falls_back_to_peer():
    assert ip_access.extract_client_ip(_Headers({}), "192.168.8.81", trust_proxy=True) == "192.168.8.81"
    assert ip_access.extract_client_ip({}, None) == ""


# ---------------------------------------------------------------------------
# Кэш загрузки правил (фейковая async-фабрика БД)
# ---------------------------------------------------------------------------

class _FakeRow:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return _SettingLike(self._value)


class _SettingLike:
    def __init__(self, value):
        self.value = value


class _FakeDB:
    def __init__(self, value):
        self._value = value

    async def execute(self, *args, **kwargs):
        return _FakeRow(self._value)

    async def close(self):
        pass


def _factory(value):
    calls = {"n": 0}

    def make():
        calls["n"] += 1
        return _FakeDB(value)

    make.calls = calls
    return make


def test_get_rules_cached_loads_and_normalizes():
    ip_access.invalidate_cache()
    factory = _factory(
        {
            "mode": "blacklist",
            "whitelist": [],
            "blacklist": ["203.0.113.10/24", "8.8.8.8", "junk"],
            "trust_proxy": True,
        }
    )
    import asyncio

    rules = asyncio.run(ip_access.get_rules_cached(factory))
    assert rules["mode"] == "blacklist"
    assert rules["blacklist"] == ["203.0.113.0/24", "8.8.8.8"]
    assert rules["trust_proxy"] is True


def test_get_rules_cached_hits_cache_and_invalidate():
    ip_access.invalidate_cache()
    factory = _factory({"mode": "off", "whitelist": [], "blacklist": []})
    import asyncio

    asyncio.run(ip_access.get_rules_cached(factory))
    asyncio.run(ip_access.get_rules_cached(factory))
    asyncio.run(ip_access.get_rules_cached(factory))
    assert factory.calls["n"] == 1  # кэш: БД дёрнули один раз

    ip_access.invalidate_cache()
    asyncio.run(ip_access.get_rules_cached(factory))
    assert factory.calls["n"] == 2  # после сброса — читаем заново


def test_get_rules_cached_swallows_db_errors():
    ip_access.invalidate_cache()
    import asyncio

    class _BrokenDB:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("db down")

        async def close(self):
            pass

    def broken_factory():
        return _BrokenDB()

    rules = asyncio.run(ip_access.get_rules_cached(broken_factory))
    # При ошибке чтения БД фильтр не блокирует трафик (режим off).
    assert rules["mode"] == "off"


# ---------------------------------------------------------------------------
# Дефолт по умолчанию: белый список с офисной сетью 192.168.5.0/24.
# ---------------------------------------------------------------------------

class _EmptyRow:
    def scalar_one_or_none(self):
        return None


class _EmptyDB:
    async def execute(self, *args, **kwargs):
        return _EmptyRow()

    async def close(self):
        pass


def test_default_ip_control_is_office_whitelist():
    """Без сохранённой настройки: рабочие сети 192.168.5.0/24 и 192.168.8.0/24
    доступны сразу, всё остальное — нет."""
    import asyncio

    from app.services.settings import DEFAULT_SETTINGS, get_ip_control

    # Дефолт в DEFAULT_SETTINGS (идёт в seed для свежей БД).
    default = DEFAULT_SETTINGS["ip_control"]["value"]
    assert default["mode"] == "whitelist"
    assert default["whitelist"] == ["192.168.5.0/24", "192.168.8.0/24"]

    cfg = asyncio.run(get_ip_control(_EmptyDB()))
    assert cfg["mode"] == "whitelist"
    assert cfg["whitelist"] == ["192.168.5.0/24", "192.168.8.0/24"]

    # IP админа (192.168.5.238) и клиенты из сети сервера (192.168.8.39) — доступ есть.
    for ip in ("192.168.5.238", "192.168.8.39", "192.168.8.81"):
        assert ip_access.client_ip_allowed(
            ip, cfg["mode"], cfg["whitelist"], cfg["blacklist"]
        ) is True, ip
    # Чужой адрес извне — закрыт по умолчанию.
    assert ip_access.client_ip_allowed(
        "8.8.8.8", cfg["mode"], cfg["whitelist"], cfg["blacklist"]
    ) is False


# ---------------------------------------------------------------------------
# Журнал попыток подключения (ip_access_log).
# Используем фикстуру client, чтобы lifespan создал таблицы в тестовой БД.
# ---------------------------------------------------------------------------

def test_ip_access_log_persist_summary_recent_clear(client):
    import asyncio

    from app.services import ip_access

    async def run():
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            await ip_access.clear_attempts(db)

        await ip_access._persist_attempts(
            [
                {"ip": "8.8.8.8", "allowed": False, "mode": "whitelist", "path": "/login", "user_agent": "x"},
                {"ip": "8.8.8.8", "allowed": False, "mode": "whitelist", "path": "/", "user_agent": "x"},
                {"ip": "192.168.8.55", "allowed": True, "mode": "whitelist", "path": "/", "user_agent": "x"},
            ]
        )

        async with async_session_factory() as db:
            summ = await ip_access.get_attempts_summary(db)
            recent = await ip_access.get_recent_attempts(db)
            cleared = await ip_access.clear_attempts(db)
            after = await ip_access.get_attempts_summary(db)
        return summ, recent, cleared, after

    summ, recent, cleared, after = asyncio.run(run())
    by_ip = {s["ip"]: s for s in summ}
    assert by_ip["8.8.8.8"]["total"] == 2
    assert by_ip["8.8.8.8"]["blocked"] == 2
    assert by_ip["192.168.8.55"]["total"] == 1
    assert by_ip["192.168.8.55"]["blocked"] == 0
    assert sorted(r["ip"] for r in recent) == ["192.168.8.55", "8.8.8.8", "8.8.8.8"]
    assert cleared == 3
    assert after == []


def test_record_attempt_enqueues_and_flush(client):
    import asyncio

    from app.services import ip_access

    async def run():
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            await ip_access.clear_attempts(db)

        ip_access.record_attempt("9.9.9.9", False, "blacklist", "/login", "ua")
        ip_access.record_attempt("10.0.0.2", True, "blacklist", "/", None)
        await ip_access.flush_log()

        async with async_session_factory() as db:
            return await ip_access.get_attempts_summary(db)

    summ = asyncio.run(run())
    by_ip = {s["ip"]: s for s in summ}
    assert by_ip["9.9.9.9"]["total"] == 1
    assert by_ip["9.9.9.9"]["blocked"] == 1
    assert by_ip["10.0.0.2"]["total"] == 1
    assert by_ip["10.0.0.2"]["blocked"] == 0
