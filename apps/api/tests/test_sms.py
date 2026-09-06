"""Тесты SMS-уведомлений: авто-SMS мастеру при назначении + «Ремонт закончен»."""

import asyncio

from app.services.sms import (
    _gateway_phone,
    build_master_sms,
    build_ready_sms,
    send_master_assignment_sms,
)


# --- чистые функции (без сети) -------------------------------------------------

def test_gateway_phone_normalization():
    assert _gateway_phone("+993 71 693009") == "+99371693009"
    assert _gateway_phone("+79998887766") == "+79998887766"
    assert _gateway_phone("99371693009") == "+99371693009"
    assert _gateway_phone("") == ""


def _mk_repair(**over):
    class _C:
        def __init__(self, name, phone):
            self.full_name = name
            self.phone = phone

    class _R:
        pass

    r = _R()
    r.number = over.get("number", "TV-ASG-2026-00001")
    r.device_type = over.get("device_type", "ТВ")
    r.brand = over.get("brand", "Samsung")
    r.model = over.get("model", "UE55")
    r.serial = over.get("serial", None)
    r.fault_client = over.get("fault_client", "не включается")
    r.eta_days = over.get("eta_days", 3)
    r.client = _C(over.get("client_name", "Иван"), over.get("client_phone", "+99361000001"))
    return r


def test_master_sms_template_contains_repair_data():
    r = _mk_repair()
    text = build_master_sms("Мастер Анна", r)
    assert "TV-ASG-2026-00001" in text
    assert "Samsung UE55" in text
    assert "не включается" in text
    assert "Иван" in text


def test_ready_sms_template():
    r = _mk_repair()
    text = build_ready_sms(r)
    assert r.number in text
    assert "Иван" in text
    assert "готова к выдаче" in text or "отремонтирован" in text


# --- «Ремонт закончен» endpoint -------------------------------------------------

def _mk_repair_via_api(client, headers, city_id, key, name="Клиент SMS", phone="+993 71 111222"):
    r = client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": city_id,
            "client": {"full_name": name, "phone": phone, "consent_pdn": True},
            "device_type": "ТВ",
            "brand": "Samsung",
            "model": "UE55",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_finish_repair_marks_ready_and_returns_sms(
    client, operator_headers, city_id
):
    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-finish-1")
    r = client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repair"]["status"] == "Готово к выдаче"
    assert body["repair"]["ready_at"] is not None
    assert body["sms"]["to"] == "+993 71 111222"
    assert repair["number"] in body["sms"]["text"]


def test_finish_forbidden_for_master(
    client, admin_headers, operator_headers, master_headers, city_id
):
    # Мастер из conftest (роль master). Найдём его id.
    users = client.get("/api/admin/users", headers=admin_headers).json()
    master = next(u for u in users if u["email"] == "master@msb.local")

    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-finish-2")
    # Назначаем мастера — он получает доступ к ремонту.
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"master_ids": [master["id"]]},
    )
    assert r.status_code == 200, r.text
    # Доступ у мастера есть, но «Ремонт закончен» — только админ/оператор.
    assert client.get(f"/api/repairs/{repair['id']}", headers=master_headers).status_code == 200
    assert client.post(f"/api/repairs/{repair['id']}/finish", headers=master_headers).status_code == 403


def test_finish_sms_send(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-finish-3")
    sent = {}
    async def _fake_send(phone, text, db=None):
        sent["phone"] = phone
        sent["text"] = text
        return {"ok": True, "detail": "http_200"}
    monkeypatch.setattr("app.routers.repairs.send_sms", _fake_send)

    r = client.post(
        f"/api/repairs/{repair['id']}/finish-sms",
        headers=operator_headers,
        json={"text": "Мой текст клиенту"},
    )
    assert r.status_code == 200, r.text
    assert sent["phone"].replace(" ", "") == "+99371111222"
    assert sent["text"] == "Мой текст клиенту"
    # Зафиксировано событие в истории.
    detail = client.get(f"/api/repairs/{repair['id']}", headers=operator_headers).json()
    types = [e["type"] for e in detail["events"]]
    assert "notify" in types


def test_finish_sms_send_failure(client, operator_headers, city_id, monkeypatch):
    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-finish-4")
    async def _fake_fail(phone, text, db=None):
        return {"ok": False, "detail": "http_500"}
    monkeypatch.setattr("app.routers.repairs.send_sms", _fake_fail)
    r = client.post(
        f"/api/repairs/{repair['id']}/finish-sms",
        headers=operator_headers,
        json={"text": "текст"},
    )
    assert r.status_code == 502


# --- авто-SMS мастеру при назначении --------------------------------------------

def test_auto_sms_to_master_on_assignment(
    client, admin_headers, operator_headers, city_id, monkeypatch
):
    # Мастер с телефоном.
    master = client.post(
        "/api/admin/users", headers=admin_headers,
        json={"name": "Мастер SMS", "email": "mastersms@msb.local",
              "password": "pass123", "role": "master", "phone": "+993 62 333444"},
    ).json()

    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-assign-1")

    calls = []
    async def _fake_sms(m, rp, db=None):
        calls.append((str(m.id), str(rp.id)))
        return {"ok": True}
    monkeypatch.setattr("app.routers.repairs.send_master_assignment_sms", _fake_sms)

    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=operator_headers,
        json={"master_ids": [master["id"]]},
    )
    assert r.status_code == 200, r.text
    assert (master["id"], repair["id"]) in calls


def test_auto_sms_to_master_on_intake_with_master(
    client, admin_headers, operator_headers, city_id, monkeypatch
):
    """Оператор при приёмке сразу указал мастера — авто-SMS уходит тоже."""
    master = client.post(
        "/api/admin/users", headers=admin_headers,
        json={"name": "Мастер Приёмка", "email": "masterintake@msb.local",
              "password": "pass123", "role": "master", "phone": "+993 62 555000"},
    ).json()

    calls = []
    async def _fake_sms(m, rp, db=None):
        calls.append((str(m.id), str(rp.id)))
        return {"ok": True}
    monkeypatch.setattr("app.routers.repairs.send_master_assignment_sms", _fake_sms)

    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "sms-intake-master-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Клиент приёмка", "phone": "+993 71 000111", "consent_pdn": True},
            "device_type": "ТВ",
            "master_id": master["id"],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "Диагностика"
    assert (master["id"], r.json()["id"]) in calls


def test_sms_when_master_assigned_after_intake(
    client, admin_headers, operator_headers, city_id, monkeypatch
):
    """Мастер принял технику (без назначения — «Мастер» пустой, SMS нет),
    затем оператор назначил мастера на ремонт — SMS уходит назначенному."""
    login = client.post(
        "/api/admin/users", headers=admin_headers,
        json={"name": "Мастер Сам", "email": "masterself@msb.local",
              "password": "pass123", "role": "master", "phone": "+993 62 666000"},
    ).json()
    token = client.post(
        "/api/auth/login",
        json={"email": "masterself@msb.local", "password": "pass123"},
    ).json()["access_token"]
    self_headers = {"Authorization": f"Bearer {token}"}

    calls = []
    async def _fake_sms(m, rp, db=None):
        calls.append((str(m.id), str(rp.id)))
        return {"ok": True}
    monkeypatch.setattr("app.routers.repairs.send_master_assignment_sms", _fake_sms)

    # Приёмка мастером: он себя не назначает, SMS не уходит.
    r = client.post(
        "/api/repairs",
        headers={**self_headers, "Idempotency-Key": "sms-self-accept-1"},
        json={
            "city_id": city_id,
            "client": {"full_name": "Клиент сам мастер", "phone": "+993 71 000222", "consent_pdn": True},
            "device_type": "ТВ",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["master_id"] is None
    assert calls == []

    # Оператор назначает мастера — SMS уходит.
    p = client.patch(
        f"/api/repairs/{r.json()['id']}",
        headers=operator_headers,
        json={"master_ids": [login["id"]]},
    )
    assert p.status_code == 200, p.text
    assert (login["id"], r.json()["id"]) in calls


def test_auto_sms_to_master_when_admin_assigns_self_via_patch(
    client, admin_headers, operator_headers, city_id, monkeypatch
):
    """Мультиролевой пользователь (админ, также мастер) назначает ремонт сам
    себе через PATCH — уведомление в личку не нужно (сам себе), но SMS на его
    телефон (если указан в профиле) всё равно должно уйти.
    """
    # Обновим у самого админа телефон и добавим ему роль master (union прав).
    users = client.get("/api/admin/users", headers=admin_headers).json()
    admin_user = next(u for u in users if u["email"] == "admin@msb.local")
    r = client.patch(
        f"/api/admin/users/{admin_user['id']}",
        headers=admin_headers,
        json={"phone": "+993 62 888000", "roles": ["admin", "master"]},
    )
    assert r.status_code == 200, r.text

    repair = _mk_repair_via_api(client, operator_headers, city_id, "sms-self-patch-1")

    calls = []
    async def _fake_sms(m, rp, db=None):
        calls.append((str(m.id), str(rp.id)))
        return {"ok": True}
    monkeypatch.setattr("app.routers.repairs.send_master_assignment_sms", _fake_sms)

    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=admin_headers,
        json={"master_ids": [admin_user["id"]]},
    )
    assert r.status_code == 200, r.text
    assert (admin_user["id"], repair["id"]) in calls


def test_master_sms_skipped_without_phone(monkeypatch):
    """send_master_assignment_sms не звонит на шлюз, если у мастера нет номера."""
    class _M:
        name = "Мастер"
        phone = None
    hit = []
    async def _fake_send(phone, text, db=None):
        hit.append(phone)
        return {"ok": True}
    monkeypatch.setattr("app.services.sms.send_sms", _fake_send)

    res = asyncio.run(send_master_assignment_sms(_M(), _mk_repair()))
    assert res["ok"] is False
    assert hit == []


# --- admin: настройки SMS-шлюза + шаблоны ---------------------------------------

def test_admin_sms_config_default(client, admin_headers):
    r = client.get("/api/admin/sms", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "server" in body and "templates" in body
    assert body["server"]["enabled"] is False
    assert body["templates"]["master_assign"] == ""
    assert body["templates"]["ready"] == ""
    assert "master_name" in body["template_fields"]["master_assign"]
    assert "client_name" in body["template_fields"]["ready"]


def test_admin_sms_config_forbidden_for_operator(client, operator_headers):
    r = client.get("/api/admin/sms", headers=operator_headers)
    assert r.status_code == 403


def test_admin_sms_config_save_and_mask_password(client, admin_headers):
    r = client.put(
        "/api/admin/sms",
        headers=admin_headers,
        json={
            "enabled": True,
            "url": "https://192.168.5.238/api/3rdparty/v1/messages",
            "username": "56FNPL",
            "password": "uv9bmvwgdrcs5z",
            "verify_ssl": False,
            "timeout_sec": 8,
        },
    )
    assert r.status_code == 200, r.text
    saved = r.json()["server"]
    assert saved["url"] == "https://192.168.5.238/api/3rdparty/v1/messages"
    assert saved["username"] == "56FNPL"
    assert saved["password"] == "•" * 8  # пароль маскируется в ответе

    # Повторный GET подтверждает, что значения реально сохранились в БД.
    r2 = client.get("/api/admin/sms", headers=admin_headers)
    cfg = r2.json()["server"]
    assert cfg["enabled"] is True
    assert cfg["username"] == "56FNPL"

    # PUT без пароля (или с маской) не должен затирать сохранённый пароль —
    # проверяем это косвенно через успешную реальную отправку теста ниже.


def test_admin_sms_config_save_keeps_password_when_masked(client, admin_headers):
    client.put(
        "/api/admin/sms",
        headers=admin_headers,
        json={"enabled": True, "url": "https://gw.example", "username": "u", "password": "secret123"},
    )
    r = client.put(
        "/api/admin/sms",
        headers=admin_headers,
        json={"enabled": True, "url": "https://gw.example", "username": "u", "password": "••••••••"},
    )
    assert r.status_code == 200, r.text

    # send_sms достаёт пароль из настроек — подменим httpx, чтобы убедиться,
    # что реально ушёл "secret123", а не маска.
    import app.services.sms as sms_module

    captured = {}

    class _FakeResp:
        status_code = 200
        text = "ok"

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, auth=None):
            captured["auth"] = auth
            captured["url"] = url
            return _FakeResp()

    monkeypatch_target = sms_module.httpx
    orig_async_client = monkeypatch_target.AsyncClient
    sms_module.httpx.AsyncClient = _FakeClient
    try:
        import asyncio

        from app.db.session import async_session_factory

        async def _run():
            async with async_session_factory() as db:
                return await sms_module.send_sms("+99361000000", "тест", db=db)

        result = asyncio.run(_run())
    finally:
        sms_module.httpx.AsyncClient = orig_async_client

    assert result["ok"] is True
    assert captured["auth"] == ("u", "secret123")


def test_admin_sms_config_requires_url_when_enabled(client, admin_headers):
    r = client.put(
        "/api/admin/sms",
        headers=admin_headers,
        json={"enabled": True, "url": "", "username": "u", "password": "p"},
    )
    assert r.status_code == 400


def test_admin_sms_templates_save_and_use(
    client, admin_headers, operator_headers, city_id, monkeypatch
):
    r = client.put(
        "/api/admin/sms/templates",
        headers=admin_headers,
        json={
            "master_assign": "Мастер {master_name}, ремонт {number}, {device}",
            "ready": "Клиент {client_name}, заказ {number} готов",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["templates"]["ready"].startswith("Клиент")

    # Отдельный номер: клиент с номером по умолчанию уже создан другим тестом,
    # а приёмка больше НЕ переименовывает существующего клиента молча
    # (расхождение имени фиксируется в журнале аудита).
    repair = _mk_repair_via_api(
        client, operator_headers, city_id, "sms-tpl-1",
        name="Пётр", phone="+993 71 555666",
    )
    r2 = client.post(f"/api/repairs/{repair['id']}/finish", headers=operator_headers)
    assert r2.status_code == 200, r2.text
    text = r2.json()["sms"]["text"]
    assert text == f"Клиент Пётр, заказ {repair['number']} готов"


def test_admin_sms_templates_forbidden_for_operator(client, operator_headers):
    r = client.put(
        "/api/admin/sms/templates",
        headers=operator_headers,
        json={"master_assign": "x", "ready": "y"},
    )
    assert r.status_code == 403


def test_admin_sms_test_endpoint(client, admin_headers, monkeypatch):
    async def _fake_send(phone, text, db=None):
        return {"ok": True, "detail": "http_200"}

    monkeypatch.setattr("app.services.sms.send_sms", _fake_send)
    r = client.post(
        "/api/admin/sms/test",
        headers=admin_headers,
        json={"phone": "+993 61 000000"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_admin_sms_test_endpoint_failure(client, admin_headers, monkeypatch):
    async def _fake_fail(phone, text, db=None):
        return {"ok": False, "detail": "http_500"}

    monkeypatch.setattr("app.services.sms.send_sms", _fake_fail)
    r = client.post(
        "/api/admin/sms/test",
        headers=admin_headers,
        json={"phone": "+993 61 000000"},
    )
    assert r.status_code == 502


def test_master_sms_sent_with_phone(monkeypatch):
    """При наличии номера шлём SMS по шаблону на нормализованный телефон."""
    class _M:
        name = "Мастер Анна"
        phone = "+993 62 333444"
    sent = {}
    async def _fake_send(phone, text, db=None):
        sent["phone"] = phone
        sent["text"] = text
        return {"ok": True}
    monkeypatch.setattr("app.services.sms.send_sms", _fake_send)

    res = asyncio.run(send_master_assignment_sms(_M(), _mk_repair()))
    assert res["ok"] is True
    # send_sms сам приводит номер к виду шлюза (+993..., без пробелов); сюда
    # передаётся как в БД.
    assert sent["phone"] == "+993 62 333444"
    assert "Мастер Анна" in sent["text"]
    assert "TV-ASG-2026-00001" in sent["text"]
