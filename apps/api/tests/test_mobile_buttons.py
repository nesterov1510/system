"""Кнопки в шапке на телефоне: «Приёмка» должна быть видна и нажимаема.

Раньше кнопки из `block topbar_actions` лежали прямо в flex-строке шапки. На
узком экране строку делят кнопка меню (38px), заголовок, колокольчик и профиль,
поэтому «➕ Приёмка» сплющивалась в нечитаемую щель высотой 34px. Теперь:

* действия страницы завернуты в свой контейнер `.topbar-actions`, который с
  700px переносится на отдельную строку во всю ширину (две равные кнопки);
* «Приёмка» — главная кнопка (`.btn.primary`, оранжевая с тенью), а не тёмная
  второстепенная;
* высота нажимаемой области на телефоне — 44px и больше.
"""
import re
from pathlib import Path

import pytest

CSS_DIR = Path(__file__).resolve().parent.parent / "app" / "webui" / "static" / "msb"


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return dict(r.cookies)


def _actions(html):
    """Содержимое контейнера действий в шапке (или None, если его нет)."""
    m = re.search(
        r'<div class="topbar-actions">(.*?)</div>\s*<a class="topbar-bell',
        html,
        re.S,
    )
    return m.group(1) if m else None


def _media_block(css, max_width):
    """Тело правила @media(max-width:NNNpx) — по совпадению скобок."""
    start = css.index(f"@media(max-width:{max_width}px)")
    i = css.index("{", start)
    depth = 0
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[i + 1 : j]
    raise AssertionError("незакрытая фигурная скобка в @media")


def _media_rule(css, max_width, selector):
    """Объявления правила `selector` внутри @media(max-width:NNNpx)."""
    body = _media_block(css, max_width)
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", body)
    assert m, f"в @media(max-width:{max_width}px) нет правила {selector}"
    return m.group(1)


def _px(declarations, prop):
    m = re.search(rf"{prop}\s*:\s*(\d+(?:\.\d+)?)px", declarations)
    assert m, f"в «{declarations}» нет {prop} в px"
    return float(m.group(1))


@pytest.fixture(autouse=True)
def _clean_cookie_jar(client):
    yield
    client.cookies.clear()


# ---------------------------------------------------------------------------
# Разметка шапки
# ---------------------------------------------------------------------------
def test_actions_are_wrapped_and_intake_is_primary_cta(client):
    """«Приёмка» — главная оранжевая кнопка, обе кнопки в своём контейнере."""
    cookies = _login(client)
    html = client.get("/repairs", cookies=cookies).text
    actions = _actions(html)
    assert actions is not None, "нет контейнера .topbar-actions в шапке списка"
    assert '<a class="btn sm primary" href="/repairs/new">➕ Приёмка</a>' in actions
    assert '<a class="btn sm sec" href="/repairs?view=board">Доска</a>' in actions


def test_intake_cta_on_board_and_clients_pages(client):
    """Та же приёмка на доске и в клиентах."""
    cookies = _login(client)
    for path, expected in (
        ("/repairs?view=board", "➕ Приёмка"),
        ("/clients", "➕ Новая приёмка"),
    ):
        actions = _actions(client.get(path, cookies=cookies).text)
        assert actions is not None, f"нет .topbar-actions на {path}"
        assert f'class="btn sm primary" href="/repairs/new">{expected}</a>' in actions


def test_pages_without_actions_render_no_container(client):
    """Пустой контейнер не должен оставлять в шапке пустой второй ряд."""
    cookies = _login(client)
    for path in ("/dashboard", "/repairs/new"):
        html = client.get(path, cookies=cookies).text
        assert 'class="topbar-actions"' not in html, f"пустой контейнер на {path}"


def test_repair_card_delete_button_stays_square(client, admin_headers, city_id):
    """«🗑» не растягивается на пол-экрана: иконка остаётся квадратной."""
    r = client.post(
        "/api/repairs",
        headers={**admin_headers, "Idempotency-Key": "mobile-buttons-card-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Мобильный Клиент", "phone": "+993 61 7766554"},
            "device_type": "Телевизоры",
            "brand": "LG",
            "model": "43UP75",
            "serial": "SN776655",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    repair_id = r.json()["id"]

    cookies = _login(client)
    html = client.get(f"/repairs/{repair_id}", cookies=cookies).text
    actions = _actions(html)
    assert actions is not None
    assert '<button class="btn sm red icon"' in actions
    assert '<form class="act-icon"' in actions


# ---------------------------------------------------------------------------
# CSS: перенос на свою строку и высота под палец
# ---------------------------------------------------------------------------
def test_mobile_topbar_wraps_actions_to_own_row():
    """С 700px шапка в два ряда, контейнер действий — во всю ширину."""
    css = (CSS_DIR / "base.css").read_text(encoding="utf-8")
    topbar = _media_rule(css, 700, ".topbar")
    assert "flex-wrap:wrap" in topbar
    assert "height:auto" in topbar

    actions = _media_rule(css, 700, ".topbar-actions")
    assert "flex:1 1 100%" in actions, "контейнер не переносится на свою строку"
    assert "flex-wrap:wrap" in actions

    items = _media_rule(css, 700, ".topbar-actions>*")
    assert "flex:1 1 140px" in items, "кнопки в ряду должны делить ширину поровну"

    button = _media_rule(css, 700, ".topbar-actions .btn")
    assert "width:100%" in button
    assert "white-space:normal" in button


def test_touch_targets_are_at_least_44px_on_mobile():
    """На телефоне нажимаемая область кнопки — не меньше 44px."""
    css = (CSS_DIR / "forms.css").read_text(encoding="utf-8")
    assert _px(_media_rule(css, 820, ".btn"), "min-height") >= 44
    assert _px(_media_rule(css, 820, ".btn.sm"), "min-height") >= 44


def test_primary_button_is_visually_stronger_than_plain():
    """Главная кнопка отличается от обычной: градиент и тень против плоского фона."""
    css = (CSS_DIR / "forms.css").read_text(encoding="utf-8")
    primary = re.search(r"\.btn\.primary,\.btn-primary,\.btn\.cta\{([^}]*)\}", css)
    assert primary, "нет правила главной кнопки"
    assert "linear-gradient" in primary.group(1)
    assert "box-shadow" in primary.group(1)

    plain = re.search(r"^\.btn\{([^}]*)\}", css, re.M)
    assert plain and "linear-gradient" not in plain.group(1)
