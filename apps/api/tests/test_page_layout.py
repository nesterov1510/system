"""Конструктор блоков страницы: порядок сохраняется лично админу.

Админ нажимает «🧩 Конструктор блоков» на карточке ремонта или во вкладке
«Все ремонты», переставляет блоки (стрелками или перетаскиванием) и
сохраняет — порядок уходит в POST /ui/layout и пишется в user_page_layouts
по user_id, поэтому у каждого своя раскладка.
"""
import asyncio
import re

import pytest

from app.webui.layout import PAGE_BLOCKS, block_keys, normalize

CARD = "repair_card"
LIST = "repairs_list"


# --------------------------------------------------------------------------
# Хелперы
# --------------------------------------------------------------------------
def _run(fn):
    """Выполнить асинхронную функцию с сессией БД (тесты синхронные)."""
    from app.db.session import async_session_factory

    async def _wrap():
        async with async_session_factory() as db:
            return await fn(db)

    return asyncio.run(_wrap())


def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return dict(r.cookies)


def _make_repair(client, headers, key, phone):
    cities = client.get("/api/admin/cities", headers=headers).json()
    r = client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": cities[0]["id"],
            "client": {"full_name": "Клиент Конструктора", "phone": phone},
            "device_type": "Телевизоры",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _set_order(client, cookies, page, order, nxt="/repairs"):
    r = client.post(
        "/ui/layout",
        cookies=cookies,
        data={"page": page, "order": ",".join(order), "next": nxt},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:200]
    return r


def _orders(html, page):
    """{имя блока: order} — как его отрендерил шаблон."""
    out = {}
    for name in block_keys(page):
        m = re.search(rf'data-block="{name}"[^>]*\s+style="order:(\d+)"', html)
        assert m, f"блок {name} не отрендерен с order"
        out[name] = int(m.group(1))
    return out


@pytest.fixture(autouse=True)
def _clean_cookie_jar(client):
    yield
    client.cookies.clear()


@pytest.fixture()
def second_admin(client, admin_headers):
    """Второй админ — проверить, что раскладка не общая."""
    email = "layout2@msb.local"
    existing = {u["email"] for u in client.get("/api/admin/users", headers=admin_headers).json()}
    if email not in existing:
        r = client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={
                "name": "Второй админ",
                "email": email,
                "password": "layout123",
                "role": "admin",
            },
        )
        assert r.status_code == 201, r.text
    return {"email": email, "password": "layout123"}


# --------------------------------------------------------------------------
# Сервис раскладки
# --------------------------------------------------------------------------
def test_blocks_registered_for_both_pages():
    assert block_keys(CARD) == ["hero", "passport", "fault", "parts", "pay", "log"]
    assert block_keys(LIST) == ["toolbar", "legend", "bulk", "table", "pager"]
    assert set(PAGE_BLOCKS) == {CARD, LIST}
    for page, blocks in PAGE_BLOCKS.items():
        assert blocks, page
        assert all(label.strip() for _key, label in blocks), page


def test_normalize_drops_unknown_and_appends_new_blocks():
    # чужие имена и дубли отбрасываются, недостающие блоки дописываются в конец
    assert normalize(CARD, ["pay", "hero", "несуществующий", "pay"]) == [
        "pay", "hero", "passport", "fault", "parts", "log",
    ]
    assert normalize(LIST, None) == block_keys(LIST)
    assert normalize(LIST, []) == block_keys(LIST)
    assert normalize("нет_такой_страницы", ["a", "b"]) == []


def test_layout_is_saved_per_user_and_updated_in_place():
    from app.db.models import User, UserPageLayout
    from app.webui.layout import get_layout, save_layout
    from sqlalchemy import func, select

    async def scenario(db):
        rows = (
            await db.execute(select(User).where(User.email.in_(["admin@msb.local", "master@msb.local"])))
        ).scalars().all()
        by_email = {u.email: u for u in rows}
        admin, master = by_email["admin@msb.local"], by_email["master@msb.local"]

        await save_layout(db, admin.id, CARD, ["log", "hero", "passport", "fault", "parts", "pay"])
        la = await get_layout(db, admin.id, CARD)
        assert la["log"] == 0 and la["hero"] == 1 and la["pay"] == 5

        # у мастера раскладка не тронута
        lm = await get_layout(db, master.id, CARD)
        assert sorted(lm, key=lambda b: lm[b]) == block_keys(CARD)

        # повторное сохранение обновляет строку, а не плодит дубли
        await save_layout(db, admin.id, CARD, ["hero", "log", "passport", "fault", "parts", "pay"])
        n = (
            await db.execute(
                select(func.count()).select_from(UserPageLayout).where(
                    UserPageLayout.user_id == admin.id, UserPageLayout.page == CARD
                )
            )
        ).scalar()
        assert n == 1
        assert (await get_layout(db, admin.id, CARD))["log"] == 1

        # другая страница хранится отдельно
        await save_layout(db, admin.id, LIST, ["table", "toolbar", "legend", "bulk", "pager"])
        assert (await get_layout(db, admin.id, LIST))["table"] == 0
        assert (await get_layout(db, admin.id, CARD))["hero"] == 0

        # раскладка админа возвращается к порядку по умолчанию
        await save_layout(db, admin.id, CARD, block_keys(CARD))
        await save_layout(db, admin.id, LIST, block_keys(LIST))

    _run(scenario)


# --------------------------------------------------------------------------
# Разметка страниц
# --------------------------------------------------------------------------
def test_card_renders_blocks_in_default_order(client, admin_headers):
    rep = _make_repair(client, admin_headers, "layout-card-1", "+99360110001")
    html = client.get(f"/repairs/{rep['id']}", cookies=_login(client)).text
    assert "data-lay-root" in html
    assert 'data-lay-bar' in html and 'action="/ui/layout"' in html
    assert f'value="{CARD}"' in html
    assert "layout.css" in html and "layout.js" in html
    assert _orders(html, CARD) == {name: i for i, name in enumerate(block_keys(CARD))}


def test_list_renders_blocks_in_default_order(client, admin_headers):
    _make_repair(client, admin_headers, "layout-list-1", "+99360110002")
    html = client.get("/repairs", cookies=_login(client)).text
    assert "data-lay-root" in html and "data-lay-bar" in html
    assert f'value="{LIST}"' in html
    assert "layout.css" in html and "layout.js" in html
    assert _orders(html, LIST) == {name: i for i, name in enumerate(block_keys(LIST))}


# --------------------------------------------------------------------------
# Сохранение порядка
# --------------------------------------------------------------------------
def test_saved_order_is_rendered_back(client, admin_headers):
    rep = _make_repair(client, admin_headers, "layout-card-2", "+99360110003")
    cookies = _login(client)
    new_order = ["log", "parts", "pay", "fault", "passport", "hero"]
    r = _set_order(client, cookies, CARD, new_order, nxt=f"/repairs/{rep['id']}")
    assert r.headers["location"] == f"/repairs/{rep['id']}"

    html = client.get(f"/repairs/{rep['id']}", cookies=cookies).text
    assert _orders(html, CARD) == {name: i for i, name in enumerate(new_order)}

    # список не пострадал от сохранения карточки
    lst = client.get("/repairs", cookies=cookies).text
    assert _orders(lst, LIST) == {name: i for i, name in enumerate(block_keys(LIST))}

    _set_order(client, cookies, CARD, block_keys(CARD))  # вернуть по умолчанию


def test_saved_list_order_survives_reload(client, admin_headers):
    _make_repair(client, admin_headers, "layout-list-2", "+99360110004")
    cookies = _login(client)
    new_order = ["table", "toolbar", "legend", "bulk", "pager"]
    _set_order(client, cookies, LIST, new_order)
    for _ in range(2):  # перезагрузка страницы ничего не сбрасывает
        html = client.get("/repairs", cookies=cookies).text
        assert _orders(html, LIST) == {name: i for i, name in enumerate(new_order)}
    _set_order(client, cookies, LIST, block_keys(LIST))


def test_order_is_personal_not_shared(client, admin_headers, second_admin):
    rep = _make_repair(client, admin_headers, "layout-card-3", "+99360110005")
    cookies = _login(client)
    _set_order(client, cookies, CARD, ["log", "hero", "passport", "fault", "parts", "pay"],
               nxt=f"/repairs/{rep['id']}")
    assert _orders(client.get(f"/repairs/{rep['id']}", cookies=cookies).text, CARD)["log"] == 0

    # второй админ видит порядок по умолчанию
    other = _login(client, **second_admin)
    html = client.get(f"/repairs/{rep['id']}", cookies=other).text
    orders = _orders(html, CARD)
    assert orders["hero"] == 0 and orders["log"] == 5

    _set_order(client, cookies, CARD, block_keys(CARD))


# --------------------------------------------------------------------------
# Доступ
# --------------------------------------------------------------------------
def test_master_cannot_save_layout(client, admin_headers):
    rep = _make_repair(client, admin_headers, "layout-card-4", "+99360110006")
    cookies = _login(client, "master@msb.local", "master123")
    r = client.post(
        "/ui/layout",
        cookies=cookies,
        data={"page": CARD, "order": "log,hero", "next": f"/repairs/{rep['id']}"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    # и у мастера порядок остался по умолчанию
    html = client.get(f"/repairs/{rep['id']}", cookies=cookies).text
    assert _orders(html, CARD)["hero"] == 0


def test_anonymous_is_redirected_to_login(client):
    r = client.post(
        "/ui/layout",
        data={"page": CARD, "order": "log", "next": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_unknown_page_and_external_next_rejected(client):
    cookies = _login(client)
    r = client.post(
        "/ui/layout",
        cookies=cookies,
        data={"page": "dashboard", "order": "a,b", "next": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 400

    r = client.post(
        "/ui/layout",
        cookies=cookies,
        data={"page": CARD, "order": ",".join(block_keys(CARD)), "next": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"


def test_constructor_is_hidden_from_non_admin(client, admin_headers):
    rep = _make_repair(client, admin_headers, "layout-card-5", "+99360110007")
    cookies = _login(client, "master@msb.local", "master123")
    html = client.get(f"/repairs/{rep['id']}", cookies=cookies).text
    assert "data-lay-bar" not in html and "layout.js" not in html
    assert "layout.css" in html  # стили общие, панель не показана
    lst = client.get("/repairs", cookies=cookies).text
    assert "data-lay-bar" not in lst


def test_card_grid_is_flat_so_blocks_can_move():
    """Блоки карточки — соседи одного контейнера, иначе `order` не сработает."""
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "app" / "webui" / "static" / "msb" / "repair.css").read_text(
        encoding="utf-8"
    )
    tpl = (Path(__file__).resolve().parent.parent / "app" / "webui" / "templates" / "repairs" / "detail.html").read_text(
        encoding="utf-8"
    )
    assert "rcard-grid" not in css and "rcard-grid" not in tpl
    assert re.search(r"\.rcard\{display:grid;grid-template-columns:", css)
    assert ".rcard>.is-wide{grid-column:1/-1}" in css
    # все блоки — прямые потомки .rcard
    card = tpl[tpl.index('<article class="rcard"'): tpl.index("</article>")]
    assert card.count('data-block="') == len(block_keys(CARD))
    for name in block_keys(CARD):
        assert f'data-block="{name}"' in card
