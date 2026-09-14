"""Номер телефона на приёмке: +993 + код оператора + 6 цифр.

Префикс +993 уже стоит в поле и не стирается, код оператора обязан быть одним
из 12, 60, 61, 62, 63, 64, 65, 71, 72, после него ровно 6 цифр. Если номер не
такой, заполняющему показывается предупреждение (скрипт) и форма не
принимается (сервер).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.services.numbering import TM_OPERATOR_CODES, validate_tm_phone


def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs/new"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return dict(r.cookies)


def _payload(client, admin_headers, phone, **extra):
    cities = client.get("/api/admin/cities", headers=admin_headers).json()
    data = {
        "city_id": cities[0]["id"],
        "full_name": "Проверка Номера",
        "phone": phone,
        "device_type": "Телевизоры",
        "brand": "Samsung",
        "model": "UE32",
        "fault_client": "не включается",
    }
    data.update(extra)
    return data


@pytest.fixture(autouse=True)
def _clean_cookie_jar(client):
    yield
    client.cookies.clear()


# --------------------------------------------------------------------------
# Правило проверки номера
# --------------------------------------------------------------------------
@pytest.mark.parametrize("code", TM_OPERATOR_CODES)
def test_all_operator_codes_are_accepted(code):
    assert validate_tm_phone(f"+993{code}123456") is None
    # пробелы и дефисы не мешают
    assert validate_tm_phone(f"+993 {code} 12-34-56") is None


@pytest.mark.parametrize("code", ["11", "13", "50", "66", "70", "73", "80", "99"])
def test_unknown_operator_code_is_rejected(code):
    err = validate_tm_phone(f"+993{code}123456")
    assert err is not None
    assert "Неверный код оператора" in err and f"«{code}»" in err
    assert "12, 60, 61, 62, 63, 64, 65, 71, 72" in err


def test_wrong_length_is_rejected():
    assert "ещё 2 цифр" in validate_tm_phone("+993612345")
    assert "ровно 6 цифр, а введено 7" in validate_tm_phone("+993612345678")
    assert "Введите код оператора" in validate_tm_phone("+993")
    assert validate_tm_phone("") == "Введите номер телефона"


def test_foreign_number_is_rejected():
    assert "должен начинаться с +993" in validate_tm_phone("+79991234567")


def test_short_local_forms_are_accepted():
    # «8 61 234567» и «61 234567» приводят к тому же номеру, что и полный
    assert validate_tm_phone("8 61 234567") is None
    assert validate_tm_phone("61234567") is None


# --------------------------------------------------------------------------
# Форма приёмки
# --------------------------------------------------------------------------
def test_intake_form_prefills_country_code(client, admin_headers):
    html = client.get("/repairs/new", params={"type": "Телевизоры"}, cookies=_login(client)).text
    m = re.search(r'<input id="tvCustomerPhone"[^>]*>', html, re.S)
    assert m, "нет поля телефона"
    tag = m.group(0)
    assert 'value="+993"' in tag, tag
    assert "required" in tag and 'data-tm-phone' in tag
    assert "/static/msb/priemka/phone.js" in html
    assert "+993 61 23 45 67" in tag  # подсказка в placeholder


def test_prefill_survives_form_redraw(client, admin_headers):
    """После ошибки формы введённый номер не затирается префиксом."""
    cookies = _login(client)
    r = client.post(
        "/repairs/new",
        cookies=cookies,
        data=_payload(client, admin_headers, "+99366123456"),
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert 'value="+99366123456"' in r.text


# --------------------------------------------------------------------------
# Серверная проверка
# --------------------------------------------------------------------------
def test_intake_rejects_bad_operator_code(client, admin_headers):
    cookies = _login(client)
    r = client.post(
        "/repairs/new",
        cookies=cookies,
        data=_payload(client, admin_headers, "+99366123456"),
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "Неверный код оператора «66»" in r.text
    assert "12, 60, 61, 62, 63, 64, 65, 71, 72" in r.text
    # ремонт не создан
    items = client.get("/api/repairs?q=99366123456", headers=admin_headers).json()["items"]
    assert items == []


def test_intake_rejects_short_number(client, admin_headers):
    r = client.post(
        "/repairs/new",
        cookies=_login(client),
        data=_payload(client, admin_headers, "+993612345"),
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "нужно ввести ещё 2 цифр" in r.text


def test_intake_accepts_valid_number(client, admin_headers):
    r = client.post(
        "/repairs/new",
        cookies=_login(client),
        data=_payload(client, admin_headers, "+993 65 445566"),
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:400]
    assert r.headers["location"].startswith("/repairs?just=accepted")
    items = client.get("/api/repairs?page_size=100", headers=admin_headers).json()["items"]
    assert [i for i in items if i.get("client_phone") == "+993 65 445566"]


def test_intake_checks_second_contact_phone(client, admin_headers):
    cookies = _login(client)
    bad = client.post(
        "/repairs/new",
        cookies=cookies,
        data=_payload(client, admin_headers, "+99361445577",
                      contact2_name="Второй", contact2_phone="+99377000111"),
        follow_redirects=False,
    )
    assert bad.status_code == 400
    assert "Телефон дополнительного контакта" in bad.text
    assert "Неверный код оператора «77»" in bad.text

    good = client.post(
        "/repairs/new",
        cookies=cookies,
        data=_payload(client, admin_headers, "+99361445578",
                      contact2_name="Второй", contact2_phone="+99371000111"),
        follow_redirects=False,
    )
    assert good.status_code == 303, good.text[:400]


def test_untouched_prefix_in_optional_phone_is_ignored(client, admin_headers):
    """Во втором контакте остался один префикс +993 — это не номер, а пустота."""
    r = client.post(
        "/repairs/new",
        cookies=_login(client),
        data=_payload(client, admin_headers, "+99361445579", contact2_phone="+993"),
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:400]


# --------------------------------------------------------------------------
# Скрипт поля (настоящий phone.js в jsdom)
# --------------------------------------------------------------------------
def _run_phone_js(html):
    node = shutil.which("node")
    if not node:
        return None
    runner = Path(__file__).resolve().parent / "js" / "phone_intake.cjs"
    script = (
        Path(__file__).resolve().parent.parent
        / "app" / "webui" / "static" / "msb" / "priemka" / "phone.js"
    )
    env = dict(os.environ, NODE_PATH=os.environ.get("NODE_PATH", "/tmp/node_modules"))
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "intake.html"
        page.write_text(html, encoding="utf-8")
        proc = subprocess.run(
            [node, str(runner), str(page), str(script)],
            capture_output=True, text=True, env=env, timeout=120,
        )
    assert proc.returncode == 0, proc.stderr[-800:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_phone_script_prefills_warns_and_blocks_submit(client, admin_headers):
    html = client.get("/repairs/new", params={"type": "Телевизоры"}, cookies=_login(client)).text
    res = _run_phone_js(html)
    if res is None or res.get("skip"):
        pytest.skip("нет node или jsdom — прогон phone.js пропущен")

    assert res["prefilled"] is True

    # Пока номер просто недописан, под полем ничего не мелькает, а блок
    # предупреждения на поле ровно один ( regression: их было по одному на
    # каждую клавишу, и старые не гасли).
    quiet = res["typingQuiet"]
    assert quiet["shown"] is False, quiet
    assert quiet["count"] == 1, quiet

    bad = res["badCode"]
    assert bad["shown"] is True and bad["badClass"] is True
    assert bad["ariaInvalid"] == "true"
    assert "Неверный код оператора «66»" in bad["text"]
    assert "12, 60, 61, 62, 63, 64, 65, 71, 72" in bad["text"]
    assert bad["count"] == 1, bad

    assert res["tooLong"]["shown"] is True and "ровно 6 цифр" in res["tooLong"]["text"]

    ok = res["valid"]
    assert ok["hidden"] is True and ok["goodClass"] is True and ok["badClassGone"] is True
    assert ok["text"] == "" and ok["count"] == 1, ok

    for code in TM_OPERATOR_CODES:
        assert res["codes"][code] is True, f"код {code} не прошёл"
    for code in ("11", "66", "70", "73", "99"):
        assert res["codes"]["bad" + code] is False, f"чужой код {code} прошёл"

    # Недописанный номер ловится, когда поле покидают, и гаснет после правки.
    short = res["shortOnBlur"]
    assert short["shown"] is True and "ещё 5 цифр" in short["text"], short
    assert res["hiddenAgainAfterFix"] is True

    assert res["prefixProtected"] is True
    assert res["deletableAfterPrefix"] is True
    assert res["submitBlockedOnBad"] is True
    assert res["submitBlockedOnEmpty"] is True
    assert res["submitAllowedOnGood"] is True

    opt = res["optionalEmptyOk"]
    assert opt["prefillOnFocus"] is True
    assert opt["submitNotBlocked"] is True

    extra = res["extraPhone"]
    assert extra["initialized"] is True
    assert extra["warned"] is True  # +99311… — код 11 недопустим
    assert extra["count"] == 1, extra
