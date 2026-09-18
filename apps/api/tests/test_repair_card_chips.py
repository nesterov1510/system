"""Карточка ремонта: чипы паспорта, меню мастера и фильтр по состоянию.

1. В паспорте появились чипы «Состояние», «Комплектация» и «Доставка»; двойной
   клик по ним открывает окно со списком отметок. Чип «Статус» переехал в
   конец блока.
2. В чипе «Доставка» отмечается, была ли доставка, и вписывается телефон
   доставщика (`delivery_courier_phone`).
3. Клик по имени мастера открывает меню: передать ремонт, назначить мастером,
   назначить помощником, убрать с ремонта.
4. В фильтре по статусу вкладки «Все ремонты» появились «готово, стоит в
   сервисе» и «выдано, но не оплачено».
5. Карточка ремонта растягивается на всю ширину экрана.
"""
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "app" / "webui" / "static" / "msb" / "repair.css").read_text(
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
            "brand": "Samsung",
            "model": "UE43",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _passport(html):
    """HTML блока «Паспорт» в карточке ремонта."""
    start = html.index("<h2>Паспорт</h2>")
    return html[start : html.index("</section>", start)]


@pytest.fixture(autouse=True)
def _clean_cookie_jar(client):
    yield
    client.cookies.clear()


# --------------------------------------------------------------- чипы паспорта
def test_passport_has_three_new_chips_and_status_last(client, admin_headers):
    rep = _make_repair(client, admin_headers, "chips-1", "Чип Паспорт", "+993 61 3300001")
    html = client.get(f"/repairs/{rep['id']}", cookies=_login(client)).text
    block = _passport(html)

    for chip_id, label in (("#pop-condition", "Состояние"), ("#pop-complect", "Комплектация"),
                           ("#pop-delivery", "Доставка")):
        assert f'data-popchip="{chip_id}"' in block, f"нет чипа {label}"
        assert f"<span class=\"ichip-k\">{label}</span>" in block, f"нет подписи {label}"

    # «Статус» — последний чип блока.
    assert block.rindex("Статус") > block.rindex("Доставка")
    # Старая полоса чипов комплектации внизу паспорта больше не нужна.
    assert 'class="rcard-tags"' not in html


def test_condition_list_saves_marks(client, admin_headers):
    rep = _make_repair(client, admin_headers, "chips-2", "Чип Состояние", "+993 61 3300002")
    cookies = _login(client)
    r = client.post(
        f"/repairs/{rep['id']}/condition",
        cookies=cookies,
        data={"items": ["Царапины", "Следы вскрытия"], "extra": "нет крышки",
              "next": f"/repairs/{rep['id']}"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    updated = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert updated["condition_notes"] == "Царапины, Следы вскрытия, нет крышки"
    html = client.get(f"/repairs/{rep['id']}", cookies=cookies).text
    assert "Царапины, Следы вскрытия, нет крышки" in html
    # В списке отмечены именно сохранённые пункты, а не все подряд.
    assert re.search(r'name="items" value="Царапины"\s+checked', html)
    assert re.search(r'name="items" value="Следы вскрытия"\s+checked', html)
    assert not re.search(r'name="items" value="Сколы"\s+checked', html)
    # Всё, чего нет в списке, уходит в поле «своими словами».
    assert 'name="extra" value="нет крышки"' in html


def test_complectation_list_saves_items(client, admin_headers):
    rep = _make_repair(client, admin_headers, "chips-3", "Чип Комплект", "+993 61 3300003")
    cookies = _login(client)
    r = client.post(
        f"/repairs/{rep['id']}/complectation",
        cookies=cookies,
        data={"items": ["Пульт", "Кабель питания"], "extra": "кронштейн",
              "next": f"/repairs/{rep['id']}"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    updated = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert updated["complectation"] == {"Пульт": True, "Кабель питания": True, "кронштейн": True}
    html = client.get(f"/repairs/{rep['id']}", cookies=cookies).text
    assert "Пульт, Кабель питания, кронштейн" in html


def test_delivery_chip_marks_delivery_and_courier_phone(client, admin_headers):
    rep = _make_repair(client, admin_headers, "chips-4", "Чип Доставка", "+993 61 3300004")
    cookies = _login(client)
    r = client.post(
        f"/repairs/{rep['id']}/delivery",
        cookies=cookies,
        data={"is_delivery": "1", "courier_phone": "+993 65 123456",
              "delivery_district": "Парахат 3", "delivery_comment": "позвонить за час",
              "next": f"/repairs/{rep['id']}"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    updated = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert updated["is_delivery"] is True
    assert updated["delivery_courier_phone"] == "+993 65 123456"
    assert updated["delivery_district"] == "Парахат 3"
    html = client.get(f"/repairs/{rep['id']}", cookies=cookies).text
    assert "🚚 да" in html and "+993 65 123456" in html
    assert 'name="courier_phone" value="+993 65 123456"' in html


def test_delivery_can_be_switched_off(client, admin_headers):
    rep = _make_repair(client, admin_headers, "chips-5", "Чип Доставка Off", "+993 61 3300005")
    cookies = _login(client)
    on = client.post(f"/repairs/{rep['id']}/delivery", cookies=cookies, follow_redirects=False,
                     data={"is_delivery": "1", "courier_phone": "+993 65 000000"})
    assert on.status_code == 303, on.text
    r = client.post(f"/repairs/{rep['id']}/delivery", cookies=cookies, follow_redirects=False,
                    data={"courier_phone": "", "delivery_district": "", "delivery_comment": ""})
    assert r.status_code == 303, r.text
    updated = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert updated["is_delivery"] is False
    assert updated["delivery_courier_phone"] is None


# ------------------------------------------------------------- меню мастера
def _masters(client, headers):
    return [u for u in client.get("/api/admin/users", headers=headers).json()
            if "master" in (u.get("roles") or [])]


def test_master_action_assign_helper_transfer_and_remove(client, admin_headers):
    rep = _make_repair(client, admin_headers, "mact-1", "Мастер Меню", "+993 61 3300011")
    cookies = _login(client)
    masters = _masters(client, admin_headers)
    assert masters, "в тестовой БД должен быть мастер"
    mid = masters[0]["id"]

    def act(action):
        return client.post(
            f"/repairs/{rep['id']}/master-action",
            cookies=cookies,
            data={"user_id": mid, "action": action, "next": f"/repairs/{rep['id']}"},
            follow_redirects=False,
        )

    assert act("master").status_code == 303
    rep_now = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert mid in rep_now["master_ids"]
    assert mid not in rep_now["helper_ids"]

    # Помощник: из мастеров убирается, в помощники добавляется.
    assert act("helper").status_code == 303
    rep_now = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert mid in rep_now["helper_ids"]
    assert mid not in rep_now["master_ids"]

    # Повышение обратно в мастера (регресс: связь переиспользуется, kind надо менять).
    assert act("master").status_code == 303
    rep_now = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert mid in rep_now["master_ids"]
    assert mid not in rep_now["helper_ids"]

    # Передать ремонт — исполнитель только он.
    assert act("transfer").status_code == 303
    rep_now = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert rep_now["master_ids"] == [mid]

    # Убрать с ремонта.
    assert act("remove").status_code == 303
    rep_now = client.get(f"/api/repairs/{rep['id']}", headers=admin_headers).json()
    assert rep_now["master_ids"] == []
    assert rep_now["helper_ids"] == []


def test_master_action_rejects_unknown_action(client, admin_headers):
    rep = _make_repair(client, admin_headers, "mact-2", "Мастер Меню 2", "+993 61 3300012")
    cookies = _login(client)
    mid = _masters(client, admin_headers)[0]["id"]
    r = client.post(f"/repairs/{rep['id']}/master-action", cookies=cookies,
                    data={"user_id": mid, "action": "teleport"})
    assert r.status_code == 400


def test_master_menu_markup_in_card(client, admin_headers):
    rep = _make_repair(client, admin_headers, "mact-3", "Мастер Меню 3", "+993 61 3300013")
    html = client.get(f"/repairs/{rep['id']}", cookies=_login(client)).text
    assert 'data-mpop' in html
    for label in ("Передать ремонт", "Назначить мастером", "Назначить помощником", "Убрать с ремонта"):
        assert label in html
    for action in ("transfer", "master", "helper", "remove"):
        assert f'data-mact="{action}"' in html


# ------------------------------------------------- фильтр «Все ремонты»
def test_status_filter_offers_two_extra_states(client, admin_headers):
    _make_repair(client, admin_headers, "flt-1", "Фильтр Состояние", "+993 61 3300021")
    html = client.get("/repairs", cookies=_login(client)).text
    assert 'value="__ready_in_service"' in html
    assert 'value="__issued_unpaid"' in html
    assert "Готово, стоит в сервисе" in html
    assert "Выдано, но не оплачено" in html


def test_status_filters_select_by_facts_not_status(client, admin_headers):
    ready = _make_repair(client, admin_headers, "flt-2", "Фильтр Готов", "+993 61 3300022")
    unpaid = _make_repair(client, admin_headers, "flt-3", "Фильтр Долг", "+993 61 3300023")
    client.patch(f"/api/repairs/{ready['id']}", headers=admin_headers, json={"status": "Завершён"})
    client.patch(f"/api/repairs/{unpaid['id']}", headers=admin_headers, json={"status": "Завершён"})
    client.post(f"/api/repairs/{unpaid['id']}/issue", headers=admin_headers)

    cookies = _login(client)
    ready_page = client.get("/repairs?status=__ready_in_service", cookies=cookies).text
    assert "Фильтр Готов" in ready_page
    assert "Фильтр Долг" not in ready_page

    unpaid_page = client.get("/repairs?status=__issued_unpaid", cookies=cookies).text
    assert "Фильтр Долг" in unpaid_page
    assert "Фильтр Готов" not in unpaid_page


def test_repair_card_stretches_full_width():
    assert re.search(r"\.rcard\{[^}]*max-width:none", CSS), "карточка должна быть на всю ширину"


# ---------------------------------------------- регрессии вёрстки (CSS/разметка)
def test_card_modals_do_not_touch_list_popup_styles():
    """.rpop* — всплывашки списка «Все ремонты» (repair-list.js).

    Регресс: своё .rpop-scrim в конце repair.css поднимало затемнение до
    z-index 440 при z-index 400 у меню, поэтому кнопка ⚡ открывала меню под
    затемнением и на него нельзя было нажать.
    """
    assert CSS.count(".rpop-scrim{") == 1, "нельзя переопределять .rpop-scrim"
    start = CSS.index(".rpop-scrim{")
    body = CSS[start : CSS.index("}", start)]
    assert "z-index:399" in body, "z-index затемнения списка должен остаться 399"
    assert ".rpop-modal" not in CSS and ".rpop__list" not in CSS


def test_card_popups_are_hidden_until_opened():
    """Регресс: окно «Доставка» висело на карточке и не закрывалось.

    Авторский `display` перебивает атрибут `hidden` из стилей браузера, поэтому
    окна скрываются через `display:none` и открываются классом `.is-open`.
    """
    for sel in (".cmodal", ".cmodal-scrim", ".mpop"):
        start = CSS.index(sel + "{")
        body = CSS[start : CSS.index("}", start)]
        assert "display:none" in body, f"{sel} должен быть скрыт по умолчанию"
        assert sel + ".is-open{" in CSS, f"у {sel} нет правила показа .is-open"


def test_card_markup_uses_cmodal_not_rpop(client, admin_headers):
    rep = _make_repair(client, admin_headers, "chips-css-1", "Чип Классы", "+993 61 3300031")
    html = client.get(f"/repairs/{rep['id']}", cookies=_login(client)).text
    assert 'class="cmodal"' in html
    assert 'class="cmodal-scrim"' in html
    assert "rpop-modal" not in html and "rpop-scrim" not in html
