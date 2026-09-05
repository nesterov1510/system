"""Регрессионные тесты на исправленные дефекты логики.

Каждый тест соответствует конкретной найденной проблеме:

===============================  ==================================================
Тест                            Что защищает
===============================  ==================================================
test_master_cannot_*            дыра в правах: мастер вёл кассу и выписывал
                                себе выплату по собственному ремонту
test_turkmen_phone_*            русская нормализация 7/8 плодила дубли клиентов
test_client_not_silently_*      приёмка молча переименовывала чужого клиента
test_phone_without_digits_*     клиенты без цифр сливались в одну запись
test_invalid_status_rejected    произвольный статус делал ремонт невидимым
test_device_prefix_*            префикс номера деградировал в "RE"
test_websocket_rejects_refresh  WS принимал refresh-токен
test_payment_event_currency     в бланке печатались рубли при валюте TMT
test_audit_log_*                журнал аудита не писался вовсе
test_rate_limiter_prunes        rate-limiter тёк по памяти
===============================  ==================================================
"""
import uuid

import pytest


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


def _make_user(client, admin_headers, email, role, name=None, phone=None):
    r = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": name or f"Тест {role}",
            "email": email,
            "password": "pass12345",
            "role": role,
            **({"phone": phone} if phone else {}),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _mk_repair(api, headers, city_id, key, client_payload=None, **overrides):
    """Создать ремонт. `client_payload` — данные клиента (имя/телефон)."""
    payload = {
        "city_id": city_id,
        "client": client_payload or {"full_name": "Клиент Тест", "phone": "+993 61 700001"},
        "device_type": "Телевизоры",
    }
    payload.update(overrides)
    r = api.post("/api/repairs", headers={**headers, "Idempotency-Key": key}, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="session")
def master_user(client, admin_headers):
    """Пользователь ТОЛЬКО с ролью master (создаётся один раз на сессию)."""
    user = _make_user(client, admin_headers, "perm-master@msb.local", "master")
    headers, _ = _login(client, "perm-master@msb.local", "pass12345")
    return {"user": user, "headers": headers}


@pytest.fixture
def master_ctx(client, master_user, operator_headers, city_id):
    """Свежий ремонт, назначенный мастеру, — на каждый тест свой."""
    repair = _mk_repair(client, operator_headers, city_id, f"perm-{uuid.uuid4().hex[:8]}")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"master_ids": [master_user["user"]["id"]]},
    )
    assert r.status_code == 200, r.text
    return {**master_user, "repair": r.json()}


# --------------------------------------------------------------------------
# 5.3 Права: мастер не распоряжается деньгами
# --------------------------------------------------------------------------
def test_master_cannot_take_payment(client, master_ctx):
    r = client.post(
        f"/api/repairs/{master_ctx['repair']['id']}/payments",
        headers=master_ctx["headers"],
        json={"amount": 5000, "method": "cash"},
    )
    assert r.status_code == 403, r.text


def test_master_cannot_set_own_payout_and_price(client, master_ctx):
    r = client.patch(
        f"/api/repairs/{master_ctx['repair']['id']}",
        headers=master_ctx["headers"],
        json={"price_final": 99999, "master_payout": 99999},
    )
    assert r.status_code == 403, r.text
    for field in ("price_final", "cost_amount", "master_payout", "paid", "price_min"):
        r = client.patch(
            f"/api/repairs/{master_ctx['repair']['id']}",
            headers=master_ctx["headers"],
            json={field: 1},
        )
        assert r.status_code == 403, f"{field}: {r.status_code} {r.text}"


def test_master_cannot_set_part_price_but_can_add_part(client, master_ctx):
    rid = master_ctx["repair"]["id"]
    # Свою цену задать нельзя — иначе исказится себестоимость.
    r = client.post(
        f"/api/repairs/{rid}/parts",
        headers=master_ctx["headers"],
        json={"name": "Деталь мастера", "qty": 1, "price": 777},
    )
    assert r.status_code == 403, r.text
    # Без цены — можно: берётся складская цена.
    r = client.post(
        f"/api/repairs/{rid}/parts",
        headers=master_ctx["headers"],
        json={"name": "Деталь мастера", "qty": 1},
    )
    assert r.status_code == 201, r.text


def test_master_cannot_remove_part(client, admin_headers, master_ctx):
    rid = master_ctx["repair"]["id"]
    add = client.post(
        f"/api/repairs/{rid}/parts",
        headers=admin_headers,
        json={"name": "Деталь на удаление", "qty": 1},
    )
    assert add.status_code == 201, add.text
    r = client.delete(
        f"/api/repairs/{rid}/parts/{add.json()['id']}", headers=master_ctx["headers"]
    )
    assert r.status_code == 403, r.text


def test_operator_can_take_payment_and_edit_finances(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, f"op-{uuid.uuid4().hex[:8]}")
    r = client.post(
        f"/api/repairs/{repair['id']}/payments",
        headers=operator_headers,
        json={"amount": 1500, "method": "cash"},
    )
    assert r.status_code == 201, r.text
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"price_final": 1500, "paid": True},
    )
    assert r.status_code == 200, r.text


def test_callcenter_cannot_take_payment(client, admin_headers, operator_headers, city_id):
    _make_user(client, admin_headers, "perm-cc@msb.local", "callcenter")
    headers, _ = _login(client, "perm-cc@msb.local", "pass12345")
    repair = _mk_repair(client, operator_headers, city_id, f"cc-{uuid.uuid4().hex[:8]}")
    r = client.post(
        f"/api/repairs/{repair['id']}/payments",
        headers=headers,
        json={"amount": 100, "method": "cash"},
    )
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------
# 5.6 Нормализация туркменских телефонов
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+993 61 234567", "99361234567"),
        ("99361234567", "99361234567"),
        ("8 61 234567", "99361234567"),   # местный формат с префиксом 8
        ("61 234567", "99361234567"),     # без кода страны
        ("+993-61-23-45-67", "99361234567"),
    ],
)
def test_turkmen_phone_normalization(raw, expected):
    from app.services.numbering import normalize_phone

    assert normalize_phone(raw) == expected


def test_foreign_phone_not_distorted():
    """Номер другой страны не должен искажаться туркменской логикой."""
    from app.services.numbering import normalize_phone

    assert normalize_phone("+7 900 123-45-67") == "79001234567"
    assert normalize_phone("+1 202 555 0143") == "12025550143"


def test_same_person_different_formats_is_one_client(client, operator_headers, city_id):
    """Один человек в трёх форматах записи — это ОДИН клиент, а не три."""
    for i, phone in enumerate(["+993 62 444555", "8 62 444555", "62444555"]):
        _mk_repair(
            client, operator_headers, city_id, f"dup-{i}-{uuid.uuid4().hex[:6]}",
            client_payload={"full_name": "Один Человек", "phone": phone},
        )
    clients = client.get("/api/repairs/clients/list", headers=operator_headers).json()
    matches = [c for c in clients if c["full_name"] == "Один Человек"]
    assert len(matches) == 1, f"ожидали 1 клиента, получили {len(matches)}: {matches}"
    assert matches[0]["repairs_count"] == 3


# --------------------------------------------------------------------------
# 5.7 Приёмка не переименовывает чужого клиента
# --------------------------------------------------------------------------
def test_client_not_silently_renamed(client, operator_headers, admin_headers, city_id):
    phone = "+993 63 777888"
    first = _mk_repair(
        client, operator_headers, city_id, f"rename-1-{uuid.uuid4().hex[:6]}",
        client_payload={"full_name": "Первый Владелец", "phone": phone},
    )
    assert first["client_name"] == "Первый Владелец"

    second = _mk_repair(
        client, operator_headers, city_id, f"rename-2-{uuid.uuid4().hex[:6]}",
        client_payload={"full_name": "Совсем Другой Человек", "phone": phone},
    )
    # Имя прежнего клиента сохранено — чужая история не «уехала» к другому.
    assert second["client_name"] == "Первый Владелец"

    # Расхождение зафиксировано в журнале аудита.
    audit = client.get(
        "/api/admin/audit", headers=admin_headers, params={"action": "client.merge_blocked"}
    )
    assert audit.status_code == 200, audit.text
    assert any(
        (row.get("meta") or {}).get("submitted_name") == "Совсем Другой Человек"
        for row in audit.json()
    ), audit.json()


def test_client_can_be_renamed_explicitly(client, admin_headers, operator_headers, city_id):
    repair = _mk_repair(
        client, operator_headers, city_id, f"patch-{uuid.uuid4().hex[:8]}",
        client_payload={"full_name": "Старое Имя", "phone": "+993 64 111222"},
    )
    r = client.patch(
        f"/api/repairs/clients/{repair['client_id']}",
        headers=admin_headers,
        json={"full_name": "Новое Имя"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Новое Имя"


# --------------------------------------------------------------------------
# 5.8 Телефон без цифр
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad_phone", ["-----", ".....", "абвгде", "++++++"])
def test_phone_without_digits_rejected(client, operator_headers, city_id, bad_phone):
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": f"bad-{uuid.uuid4().hex[:8]}"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Без Телефона", "phone": bad_phone},
            "device_type": "Телевизоры",
        },
    )
    assert r.status_code == 422, f"{bad_phone}: {r.status_code} {r.text}"


def test_blank_client_name_rejected(client, operator_headers, city_id):
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": f"blank-{uuid.uuid4().hex[:8]}"},
        json={
            "city_id": city_id,
            "client": {"full_name": "   ", "phone": "+993 65 000111"},
            "device_type": "Телевизоры",
        },
    )
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------
# 5.10 Статус валидируется по справочнику
# --------------------------------------------------------------------------
def test_invalid_status_rejected(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, f"st-{uuid.uuid4().hex[:8]}")
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"status": "СДЕЛАНО_КАК_ХОЧУ"},
    )
    assert r.status_code == 422, r.text

    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"status": "В ремонте"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "В ремонте"


# --------------------------------------------------------------------------
# 5.9 Префикс номера совпадает со справочником техники в UI
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "device_type,prefix",
    [
        ("Телевизоры", "TV"),
        ("Компьютеры", "PC"),
        ("Бытовая техника", "BT"),
        ("Другое", "OT"),
        ("ТВ", "TV"),        # legacy
        ("Монитор", "MN"),   # legacy
    ],
)
def test_device_prefix_matches_ui_catalog(device_type, prefix):
    from app.services.numbering import device_prefix

    assert device_prefix(device_type) == prefix


def test_ui_device_classes_all_have_prefix():
    """Ни один класс техники из UI не должен деградировать в 'RE'."""
    import pathlib

    from app.services.numbering import FALLBACK_PREFIX, device_prefix

    # apps/api/tests/<этот файл> -> parents[2] = apps/
    catalog = pathlib.Path(__file__).resolve().parents[2] / "web" / "lib" / "catalog.ts"
    assert catalog.is_file(), f"не найден справочник UI: {catalog}"
    values = [
        v for v in ("Телевизоры", "Компьютеры", "Бытовая техника", "Другое")
    ]
    # Проверяем, что значения действительно присутствуют в справочнике UI.
    text = catalog.read_text(encoding="utf-8")
    for value in values:
        assert f'value: "{value}"' in text, f"{value} пропал из DEVICE_CLASSES"
        assert device_prefix(value) != FALLBACK_PREFIX, f"{value} -> {FALLBACK_PREFIX}"


def test_repair_number_uses_real_prefix(client, operator_headers, city_id):
    repair = _mk_repair(
        client, operator_headers, city_id, f"num-{uuid.uuid4().hex[:8]}",
        device_type="Телевизоры",
    )
    assert repair["number"].startswith("TV-ASG-"), repair["number"]


# --------------------------------------------------------------------------
# 5.4 WebSocket отклоняет refresh-токен
# --------------------------------------------------------------------------
def test_websocket_rejects_refresh_token(client):
    r = client.post(
        "/api/auth/login", json={"email": "admin@msb.local", "password": "admin123"}
    )
    tokens = r.json()
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws?token={tokens['refresh_token']}") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_websocket_accepts_access_token(client):
    r = client.post(
        "/api/auth/login", json={"email": "admin@msb.local", "password": "admin123"}
    )
    token = r.json()["access_token"]
    with client.websocket_connect(f"/ws?token={token}") as ws:
        hello = ws.receive_json()
    assert hello["type"] == "hello"


def test_websocket_rejects_garbage_sub(client):
    """Токен с невалидным `sub` не должен ронять хендлер (500 в логах)."""
    from app.core.config import settings
    from starlette.websockets import WebSocketDisconnect

    import jwt as pyjwt

    bad = pyjwt.encode(
        {"sub": "не-uuid", "type": "access"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws?token={bad}") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


# --------------------------------------------------------------------------
# 5.12 Валюта в событиях кассы
# --------------------------------------------------------------------------
def test_payment_event_uses_configured_currency(client, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, f"cur-{uuid.uuid4().hex[:8]}")
    r = client.post(
        f"/api/repairs/{repair['id']}/payments",
        headers=operator_headers,
        json={"amount": 1234, "method": "cash"},
    )
    assert r.status_code == 201, r.text
    payment_id = r.json()["id"]

    updated = client.get(f"/api/repairs/{repair['id']}", headers=operator_headers).json()
    messages = [
        str((e.get("data") or {}).get("message", ""))
        for e in updated["events"]
        if e["type"] == "price"
    ]
    assert any("ман." in m for m in messages), messages
    assert not any("₽" in m for m in messages), messages

    r = client.delete(f"/api/payments/{payment_id}", headers=operator_headers)
    assert r.status_code == 403, "отмена платежа — только админ/менеджер"


def test_refund_requires_admin_or_manager(client, admin_headers, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, f"ref-{uuid.uuid4().hex[:8]}")
    pay = client.post(
        f"/api/repairs/{repair['id']}/payments",
        headers=operator_headers,
        json={"amount": 900, "method": "card"},
    )
    assert pay.status_code == 201, pay.text
    r = client.delete(f"/api/payments/{pay.json()['id']}", headers=admin_headers)
    assert r.status_code == 200, r.text

    updated = client.get(f"/api/repairs/{repair['id']}", headers=admin_headers).json()
    cancel_msgs = [
        str((e.get("data") or {}).get("message", ""))
        for e in updated["events"]
        if "отменён" in str((e.get("data") or {}).get("message", ""))
    ]
    assert cancel_msgs and "₽" not in cancel_msgs[0], cancel_msgs


# --------------------------------------------------------------------------
# 5.19 Журнал аудита
# --------------------------------------------------------------------------
def test_audit_log_records_money_and_deletions(client, admin_headers, operator_headers, city_id):
    repair = _mk_repair(client, operator_headers, city_id, f"aud-{uuid.uuid4().hex[:8]}")
    client.post(
        f"/api/repairs/{repair['id']}/payments",
        headers=operator_headers,
        json={"amount": 4242, "method": "transfer"},
    )

    rows = client.get(
        "/api/admin/audit",
        headers=admin_headers,
        params={"action": "payment.add", "entity_id": str(repair["id"])},
    ).json()
    assert rows, "платёж не попал в журнал аудита"
    assert rows[0]["meta"]["amount"] == 4242
    assert rows[0]["actor_name"], "в аудите не resolved имя сотрудника"

    # Удаление ремонта тоже остаётся в журнале (repair_events уходит вместе с ним).
    r = client.delete(f"/api/repairs/{repair['id']}", headers=admin_headers)
    assert r.status_code == 200, r.text
    rows = client.get(
        "/api/admin/audit",
        headers=admin_headers,
        params={"action": "repair.delete", "entity_id": str(repair["id"])},
    ).json()
    assert rows and rows[0]["meta"]["number"] == repair["number"]


def test_audit_endpoint_is_admin_only(client, operator_headers, master_headers):
    for headers in (operator_headers, master_headers):
        r = client.get("/api/admin/audit", headers=headers)
        assert r.status_code == 403, r.text


# --------------------------------------------------------------------------
# 5.13 Rate limiter не течёт
# --------------------------------------------------------------------------
def test_rate_limiter_prunes_stale_keys():
    from app.services.ratelimit import RateLimiter

    limiter = RateLimiter(limit=2, window=0.01, sweep_every=1)
    for i in range(200):
        limiter.allow(f"ip-{i}")
    assert len(limiter) == 200

    import time

    time.sleep(0.05)  # окно прошло
    limiter.allow("trigger-sweep")
    assert len(limiter) <= 1, f"пустые ключи не очищены: {len(limiter)}"


# --------------------------------------------------------------------------
# 5.22 S3-режим даёт внятную ошибку, а не ImportError
# --------------------------------------------------------------------------
def test_s3_mode_raises_clear_error(monkeypatch):
    from app.core.config import settings
    from app.services.storage import StorageNotConfigured, save_object

    monkeypatch.setattr(settings, "STORAGE_MODE", "s3", raising=False)
    import asyncio

    with pytest.raises(StorageNotConfigured) as exc:
        asyncio.run(save_object(b"data", "repairs/x/y.jpg"))
    assert "storage_s3" in str(exc.value)


# --------------------------------------------------------------------------
# 5.11 Печать без шрифтов — понятная ошибка, а не 500
# --------------------------------------------------------------------------
def test_print_without_fonts_returns_503(client, operator_headers, city_id, monkeypatch):
    from app.services import print as print_module

    repair = _mk_repair(client, operator_headers, city_id, f"font-{uuid.uuid4().hex[:8]}")
    monkeypatch.setattr(print_module, "_fonts_registered", False, raising=False)
    monkeypatch.setattr(
        print_module, "_resolve_font_paths",
        lambda: (_ for _ in ()).throw(
            print_module.FontNotAvailable("Не найден кириллический шрифт DejaVu Sans")
        ),
    )
    r = client.post(f"/api/repairs/{repair['id']}/print", headers=operator_headers)
    assert r.status_code == 503, r.text
    assert "DejaVu" in r.json()["detail"]
