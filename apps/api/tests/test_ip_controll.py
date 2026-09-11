"""Тесты модуля start_ip_controll (выбор host/port по ip_controll.env)."""
import pytest

from start_ip_controll.ip_controll import (
    _get_detected_local_ips,
    _ip_matches_rule,
    _is_valid_ip_or_network_rule,
    get_server_start_config,
    read_ip_controll_env,
)


def test_detected_local_ips_include_loopback():
    ips = _get_detected_local_ips()
    assert "127.0.0.1" in ips


@pytest.mark.parametrize("rule,ip,expected", [
    ("192.168.8.81", "192.168.8.81", True),
    ("192.168.8.81", "192.168.8.82", False),
    ("192.168.8.0/24", "192.168.8.55", True),
    ("192.168.8.0/24", "192.168.9.55", False),
])
def test_ip_rule_matching(rule, ip, expected):
    assert _ip_matches_rule(ip, rule) is expected


@pytest.mark.parametrize("rule,expected", [
    ("192.168.8.81", True),
    ("192.168.8.0/24", True),
    ("999.1.1.1", False),
    ("не-ip", False),
])
def test_rule_validation(rule, expected):
    assert _is_valid_ip_or_network_rule(rule) is expected


def test_read_env_file(tmp_path):
    env = tmp_path / "ip_controll.env"
    env.write_text(
        "# comment\nMAIN_START_PORT=9090\n\nMAIN_NA_VCEH_IP_START=True\n",
        encoding="utf-8",
    )
    data = read_ip_controll_env(env)
    assert data["MAIN_START_PORT"] == "9090"
    assert data["MAIN_NA_VCEH_IP_START"] == "True"


def test_listen_all_interfaces(monkeypatch):
    monkeypatch.setenv("MAIN_LOCAL_HOST", "False")
    monkeypatch.setenv("MAIN_NA_VCEH_IP_START", "True")
    monkeypatch.setenv("MAIN_START_PORT", "8085")
    cfg = get_server_start_config()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8085
    assert cfg.all_ip_start_enabled is True


def test_localhost_only(monkeypatch):
    monkeypatch.setenv("MAIN_LOCAL_HOST", "True")
    monkeypatch.setenv("MAIN_NA_VCEH_IP_START", "False")
    monkeypatch.setenv("MAIN_START_PORT", "7000")
    cfg = get_server_start_config()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 7000


def test_bad_port_fails(monkeypatch):
    monkeypatch.setenv("MAIN_NA_VCEH_IP_START", "True")
    monkeypatch.setenv("MAIN_START_PORT", "70000")
    with pytest.raises(RuntimeError):
        get_server_start_config()


def test_whitelist_blocks_foreign_ip(monkeypatch):
    monkeypatch.setenv("MAIN_LOCAL_HOST", "False")
    monkeypatch.setenv("MAIN_NA_VCEH_IP_START", "False")
    monkeypatch.setenv("MAIN_RAZRESHENNIYE_IP_PROVERKA", "True")
    # Сеть, в которую заведомо не входит ни один локальный адрес теста.
    monkeypatch.setenv("MAIN_KAKIYE_IP_RAZRESHEN_DLYA_START", "10.250.250.0/24")
    with pytest.raises(RuntimeError):
        get_server_start_config()


def test_whitelist_allows_loopback(monkeypatch):
    monkeypatch.setenv("MAIN_LOCAL_HOST", "False")
    monkeypatch.setenv("MAIN_NA_VCEH_IP_START", "False")
    monkeypatch.setenv("MAIN_RAZRESHENNIYE_IP_PROVERKA", "True")
    monkeypatch.setenv("MAIN_KAKIYE_IP_RAZRESHEN_DLYA_START", "127.0.0.1")
    cfg = get_server_start_config()
    assert cfg.host == "127.0.0.1"
