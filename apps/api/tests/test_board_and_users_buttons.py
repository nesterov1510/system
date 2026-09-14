"""Доска ремонтов без колонок и светлые кнопки во вкладке «Сотрудники».

1. Доска (`/repairs?view=board`) — один общий список карточек: деления на
   колонки по этапам («Новые» / «Диагностика» / «В работе») больше нет, этап
   виден в чипе статуса на карточке. Подсказка-пояснение над доской убрана.
2. Во вкладке «Сотрудники» не осталось чёрных кнопок: у кнопок-раскрытий
   (`summary` у `<details>`) не было своего стиля `.ghost`, и они получали
   чёрный фон обычной `.btn`. Теперь каждое действие светлое и со смыслом.
"""
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "app" / "webui" / "static" / "msb" / "forms.css").read_text(
    encoding="utf-8"
)


def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return dict(r.cookies)


def _make_repair(client, headers, key, name, phone):
    cities = client.get("/api/admin/cities", headers=headers).json()
    r = client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": cities[0]["id"],
            "client": {"full_name": name, "phone": phone},
            "device_type": "Телевизоры",
            "brand": "Sony",
            "model": "KD-55X80",
            "fault_client": "нет звука",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(autouse=True)
def _clean_cookie_jar(client):
    yield
    client.cookies.clear()


# -------------------------------------------------------------------- доска
def test_board_is_one_list_without_stage_columns(client, admin_headers):
    _make_repair(client, admin_headers, "board-flat-1", "Доска Плоская", "+993 61 2200011")
    cookies = _login(client)
    html = client.get("/repairs?view=board", cookies=cookies).text

    assert 'class="board"' in html
    assert 'class="bcard"' in html
    # Ни канбана, ни колонок по этапам.
    assert "kanban" not in html
    assert "kcol" not in html
    assert "Диагностика</h4>" not in html


def test_board_hint_is_removed(client, admin_headers):
    """Поясняющая строка над доской больше не печатается."""
    _make_repair(client, admin_headers, "board-hint-1", "Доска Подсказка", "+993 61 2200022")
    cookies = _login(client)
    html = client.get("/repairs?view=board", cookies=cookies).text
    assert "На доске — только активные ремонты" not in html
    assert "rlist-head" not in html


def test_board_card_keeps_status_and_opens_repair(client, admin_headers):
    """Этап не потерян: статус остался чипом, а карточка — ссылкой на ремонт."""
    rep = _make_repair(client, admin_headers, "board-card-1", "Доска Карточка", "+993 61 2200033")
    cookies = _login(client)
    html = client.get("/repairs?view=board", cookies=cookies).text
    cards = [chunk for chunk in html.split('<a class="bcard"') if "Доска Карточка" in chunk]
    assert cards, "карточка созданного ремонта не найдена на доске"
    card = cards[0]
    assert f'href="/repairs/{rep["id"]}"' in card
    assert rep["status"] in card, "статус (этап) должен быть виден на карточке"


def test_board_search_form_stays(client):
    cookies = _login(client)
    html = client.get("/repairs?view=board", cookies=cookies).text
    assert 'class="board-search"' in html
    assert 'name="view" value="board"' in html


# --------------------------------------------------------- вкладка «Сотрудники»
def test_users_tab_has_no_black_buttons(client):
    cookies = _login(client)
    html = client.get("/admin/users", cookies=cookies).text
    classes = re.findall(r'class="(btn[^"]*)"', html)
    assert classes, "на странице сотрудников должны быть кнопки"
    for cls in classes:
        # «Голой» тёмной кнопки (btn / btn sm) оставаться не должно: каждое
        # действие окрашено по смыслу.
        assert cls.split()[-1] in {"sec", "ghost", "green", "red", "primary"}, cls
    assert 'style="display:inline-block"' not in html, "инлайн-стили у кнопок убраны"


def test_users_tab_actions_use_new_classes(client):
    cookies = _login(client)
    html = client.get("/admin/users", cookies=cookies).text
    assert 'class="user-actions"' in html
    assert 'class="btn primary" type="submit">➕ Создать сотрудника</button>' in html
    # Сброс пароля — заметная оранжевая кнопка, а не чёрная «OK».
    assert 'class="btn sm primary" type="submit">Сбросить</button>' in html
    assert ">OK</button>" not in html


def test_ghost_button_style_exists_in_css():
    """Класс .ghost обязан быть описан, иначе кнопки снова станут чёрными."""
    assert re.search(r"\.btn\.ghost\{[^}]*background:#fff", CSS), "нет светлого фона у .btn.ghost"
    assert ".user-actions{" in CSS
    assert ".user-panel{" in CSS
    assert ".user-inline{" in CSS


def test_board_css_replaced_kanban():
    assert ".kanban{" not in CSS and ".kcol{" not in CSS, "стили канбана должны быть удалены"
    assert ".board{" in CSS and ".bcard{" in CSS
