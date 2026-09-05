"""Приёмка техники мастером: своя приёмка видна и печатается сразу.

Исполнителя на ремонт назначает администратор/оператор, поэтому у ремонта,
который мастер принял сам, `master_id` пустой. Раньше из-за этого мастер не
имел доступа к собственной приёмке: карточка отдавала 404, автопечать этикетки
— 403 «Нет доступа к этому ремонту», а из списка ремонт исчезал. Здесь —
регламент: доступ и печать по факту приёмки (`accepted_by`), но чужие ремонты
мастеру по-прежнему закрыты.
"""


LABEL_CONFIG = {
    "ip": "192.168.5.238",
    "port": 631,
    "mode": "cups_remote",
    "name": "3B-350B",
    "width_mm": 58,
    "height_mm": 38,
    "media": "Custom.58x38mm",
}


def _configure_label_printer(client, admin_headers):
    """Без настроенной очереди печать честно отвечает 400 — настроим, как в бою."""
    r = client.put("/api/admin/printer/label", headers=admin_headers, json=LABEL_CONFIG)
    assert r.status_code == 200, r.text


def _master_id(client, master_headers):
    me = client.get("/api/auth/me", headers=master_headers)
    assert me.status_code == 200, me.text
    return me.json()["id"]


def _intake(client, headers, city_id, key, phone="+993 61 880011", master_id=None):
    body = {
        "city_id": city_id,
        "client": {"full_name": "Клиент Мастера", "phone": phone, "consent_pdn": True},
        "device_type": "Телевизоры",
        "brand": "LG",
        "model": "32LK6100",
        "fault_client": "нет изображения",
    }
    if master_id is not None:
        body["master_id"] = master_id
    return client.post(
        "/api/repairs", headers={**headers, "Idempotency-Key": key}, json=body
    )


def test_master_intake_is_created(client, master_headers, city_id):
    r = _intake(client, master_headers, city_id, "mi-1")
    assert r.status_code == 201, r.text
    assert r.json()["number"]


def test_master_can_open_his_own_intake(client, master_headers, city_id):
    """Карточка своей приёмки доступна, даже когда исполнитель не назначен."""
    created = _intake(client, master_headers, city_id, "mi-2")
    assert created.status_code == 201, created.text
    repair_id = created.json()["id"]
    assert created.json()["master_id"] is None

    card = client.get(f"/api/repairs/{repair_id}", headers=master_headers)
    assert card.status_code == 200, card.text
    assert card.json()["number"] == created.json()["number"]


def test_master_can_print_label_for_his_own_intake(
    client, admin_headers, master_headers, city_id
):
    """Автопечать этикетки при приёмке больше не упирается в 403."""
    _configure_label_printer(client, admin_headers)
    created = _intake(client, master_headers, city_id, "mi-3")
    assert created.status_code == 201, created.text

    printed = client.post(
        f"/api/repairs/{created.json()['id']}/print-label", headers=master_headers
    )
    assert printed.status_code == 200, printed.text
    assert printed.json()["status"] == "queued"
    assert printed.json()["pdf_base64"]


def test_master_can_print_blank_for_his_own_intake(
    client, admin_headers, master_headers, city_id
):
    _configure_label_printer(client, admin_headers)
    created = _intake(client, master_headers, city_id, "mi-4")
    assert created.status_code == 201, created.text
    printed = client.post(
        f"/api/repairs/{created.json()['id']}/print", headers=master_headers
    )
    assert printed.status_code == 200, printed.text


def test_master_sees_his_intake_in_list_and_counts(client, master_headers, city_id):
    created = _intake(client, master_headers, city_id, "mi-5")
    assert created.status_code == 201, created.text
    number = created.json()["number"]

    listed = client.get("/api/repairs", headers=master_headers, params={"q": number})
    assert listed.status_code == 200, listed.text
    items = listed.json().get("items", [])
    assert any(r["number"] == number for r in items), "своя приёмка пропала из списка"

    counts = client.get("/api/repairs/stage-counts", headers=master_headers)
    assert counts.status_code == 200, counts.text
    assert counts.json()["new"] >= 1


def test_master_can_comment_his_own_intake(client, master_headers, city_id):
    created = _intake(client, master_headers, city_id, "mi-6")
    assert created.status_code == 201, created.text
    r = client.post(
        f"/api/repairs/{created.json()['id']}/events",
        headers=master_headers,
        json={"type": "comment", "message": "принял у клиента, жду диагностику"},
    )
    assert r.status_code in (200, 201), r.text


def test_master_intake_does_not_self_assign(client, master_headers, city_id):
    """Исполнителя по-прежнему назначает администратор/оператор."""
    master_id = _master_id(client, master_headers)
    r = _intake(client, master_headers, city_id, "mi-7", master_id=master_id)
    assert r.status_code == 403, r.text
    assert "администратор" in r.json()["detail"].lower()


def test_master_cannot_assign_another_master_at_intake(
    client, admin_headers, master_headers, city_id
):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    another = next(
        (
            u
            for u in users
            if u["id"] != _master_id(client, master_headers)
            and "master" in [r if isinstance(r, str) else r.get("role") for r in (u.get("roles") or [u.get("role")])]
        ),
        None,
    )
    if another is None:
        created = client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={
                "name": "Второй мастер",
                "email": "master2@msb.local",
                "password": "master123",
                "role": "master",
            },
        )
        assert created.status_code == 201, created.text
        another = created.json()

    r = _intake(client, master_headers, city_id, "mi-8", master_id=another["id"])
    assert r.status_code == 403, r.text


def test_master_still_cannot_print_foreign_repair(
    client, operator_headers, master_headers, city_id
):
    """Расширение прав только на СВОЮ приёмку: чужой ремонт закрыт."""
    foreign = _intake(client, operator_headers, city_id, "mi-9", phone="+993 61 880022")
    assert foreign.status_code == 201, foreign.text
    repair_id = foreign.json()["id"]

    assert client.post(f"/api/repairs/{repair_id}/print-label", headers=master_headers).status_code == 403
    assert client.post(f"/api/repairs/{repair_id}/print", headers=master_headers).status_code == 403
    # Чужая карточка закрыта (403 или 404 — главное, не отдаём данные).
    assert client.get(f"/api/repairs/{repair_id}", headers=master_headers).status_code in (403, 404)

    listed = client.get("/api/repairs", headers=master_headers, params={"q": foreign.json()["number"]})
    assert listed.status_code == 200
    assert not any(
        r["number"] == foreign.json()["number"] for r in listed.json().get("items", [])
    )


def test_master_keeps_access_after_operator_assigns_someone_else(
    client, admin_headers, operator_headers, master_headers, city_id
):
    """Оператор назначил другого мастера — приёмщик свою карточку не теряет."""
    _configure_label_printer(client, admin_headers)
    created = _intake(client, master_headers, city_id, "mi-10", phone="+993 61 880033")
    assert created.status_code == 201, created.text
    repair_id = created.json()["id"]

    users = client.get("/api/admin/users", headers=admin_headers).json()
    me = _master_id(client, master_headers)
    other_master = next(
        u for u in users if u["id"] != me and (u.get("role") == "master" or "master" in (u.get("roles") or []))
    )
    assigned = client.patch(
        f"/api/repairs/{repair_id}",
        headers=operator_headers,
        json={"master_ids": [other_master["id"]]},
    )
    assert assigned.status_code == 200, assigned.text

    card = client.get(f"/api/repairs/{repair_id}", headers=master_headers)
    assert card.status_code == 200, card.text
    printed = client.post(f"/api/repairs/{repair_id}/print-label", headers=master_headers)
    assert printed.status_code == 200, printed.text
