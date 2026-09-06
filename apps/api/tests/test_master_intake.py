"""Приёмка техники мастером: печать этикетки есть, чужих заказов не видно.

Правило, которое здесь зафиксировано:

* исполнитель — только назначенный (администратором или оператором);
* мастер видит в списке/доске/карточке ЛИШЬ те заказы, которые ему назначили.
  Своя приёмка без назначения в список не попадает — иначе у мастера висят
  заказы, которые ему не отдавали;
* но этикетку на свою приёмку он напечатать может, и она уходит на принтер
  автоматически при сохранении: пока исполнитель не назначен, ремонт всё ещё
  «его» (техника стоит перед ним, наклейку надо приклеить при клиенте);
* как только исполнителя назначили (даже не на него) — печать и доступ у
  приёмщика закрываются, заказ перешёл к другому мастеру.
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


# ---------------------------------------------------------------------------
# Приёмка мастером: создана, исполнитель не назначен
# ---------------------------------------------------------------------------
def test_master_intake_is_created_without_self_assignment(client, master_headers, city_id):
    r = _intake(client, master_headers, city_id, "mi-1")
    assert r.status_code == 201, r.text
    assert r.json()["number"]
    # Себя мастер исполнителем не назначает — это делает администратор/оператор.
    assert r.json()["master_id"] is None
    assert r.json()["status"] == "Принято"


def test_master_can_print_label_for_his_own_intake(
    client, admin_headers, master_headers, city_id
):
    """Автопечать этикетки при приёмке работает у мастера (раньше была 403)."""
    _configure_label_printer(client, admin_headers)
    created = _intake(client, master_headers, city_id, "mi-2")
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
    created = _intake(client, master_headers, city_id, "mi-3")
    assert created.status_code == 201, created.text
    printed = client.post(
        f"/api/repairs/{created.json()['id']}/print", headers=master_headers
    )
    assert printed.status_code == 200, printed.text


# ---------------------------------------------------------------------------
# Строгая видимость: мастер видит только назначенные ему заказы
# ---------------------------------------------------------------------------
def test_master_does_not_see_his_unassigned_intake_in_list(
    client, master_headers, city_id
):
    created = _intake(client, master_headers, city_id, "mi-4", phone="+993 61 880044")
    assert created.status_code == 201, created.text
    number = created.json()["number"]

    listed = client.get(
        "/api/repairs", headers=master_headers, params={"stage": "all", "page_size": 100}
    )
    assert listed.status_code == 200, listed.text
    numbers = [r["number"] for r in listed.json()["items"]]
    assert number not in numbers, "неназначенная своя приёмка не должна быть в списке"


def test_master_card_of_unassigned_intake_is_closed(client, master_headers, city_id):
    created = _intake(client, master_headers, city_id, "mi-5", phone="+993 61 880055")
    assert created.status_code == 201, created.text

    card = client.get(f"/api/repairs/{created.json()['id']}", headers=master_headers)
    assert card.status_code in (403, 404), card.text

    comment = client.post(
        f"/api/repairs/{created.json()['id']}/events",
        headers=master_headers,
        json={"type": "comment", "message": "комментарий"},
    )
    assert comment.status_code in (403, 404), comment.text


def test_unassigned_intake_is_not_in_master_stage_counts(client, master_headers, city_id):
    before = client.get("/api/repairs/stage-counts", headers=master_headers).json()
    created = _intake(client, master_headers, city_id, "mi-6", phone="+993 61 880066")
    assert created.status_code == 201, created.text
    after = client.get("/api/repairs/stage-counts", headers=master_headers).json()

    assert after["new"] == before["new"], "своя приёмка попала в счётчики мастера"
    assert after["all"] == before["all"]


def test_master_still_cannot_print_foreign_repair(
    client, operator_headers, master_headers, city_id
):
    """Чужая приёмка (даже неназначенная) мастеру недоступна."""
    foreign = _intake(client, operator_headers, city_id, "mi-7", phone="+993 61 880077")
    assert foreign.status_code == 201, foreign.text
    repair_id = foreign.json()["id"]

    assert (
        client.post(f"/api/repairs/{repair_id}/print-label", headers=master_headers).status_code
        == 403
    )
    assert (
        client.post(f"/api/repairs/{repair_id}/print", headers=master_headers).status_code == 403
    )
    assert client.get(f"/api/repairs/{repair_id}", headers=master_headers).status_code in (403, 404)


# ---------------------------------------------------------------------------
# Назначение исполнителя
# ---------------------------------------------------------------------------
def test_master_cannot_assign_master_at_intake(client, master_headers, city_id):
    me = _master_id(client, master_headers)
    r = _intake(client, master_headers, city_id, "mi-8", master_id=me)
    assert r.status_code == 403, r.text
    assert "администратор" in r.json()["detail"].lower()


def test_master_cannot_assign_another_master_at_intake(
    client, admin_headers, master_headers, city_id
):
    other = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Второй мастер",
            "email": "master2@msb.local",
            "password": "master123",
            "role": "master",
        },
    )
    assert other.status_code == 201, other.text

    r = _intake(client, master_headers, city_id, "mi-9", master_id=other.json()["id"])
    assert r.status_code == 403, r.text


def test_assigned_master_gets_full_access(client, operator_headers, master_headers, city_id):
    """Назначенный исполнитель видит заказ в списке, карточке и печатает его."""
    me = _master_id(client, master_headers)
    created = _intake(
        client, operator_headers, city_id, "mi-10", phone="+993 61 880088", master_id=me
    )
    assert created.status_code == 201, created.text
    repair = created.json()

    assert client.get(f"/api/repairs/{repair['id']}", headers=master_headers).status_code == 200
    listed = client.get(
        "/api/repairs", headers=master_headers, params={"stage": "all", "page_size": 100}
    )
    assert repair["number"] in [r["number"] for r in listed.json()["items"]]


def test_intake_master_loses_print_right_once_executor_assigned(
    client, admin_headers, operator_headers, master_headers, city_id
):
    """Заказ передали другому мастеру — приёмщик его больше не печатает и не видит."""
    _configure_label_printer(client, admin_headers)
    created = _intake(client, master_headers, city_id, "mi-11", phone="+993 61 880099")
    assert created.status_code == 201, created.text
    repair_id = created.json()["id"]
    assert (
        client.post(f"/api/repairs/{repair_id}/print-label", headers=master_headers).status_code
        == 200
    )

    other = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Третий мастер",
            "email": "master3@msb.local",
            "password": "master123",
            "role": "master",
        },
    )
    assert other.status_code == 201, other.text
    assigned = client.patch(
        f"/api/repairs/{repair_id}",
        headers=operator_headers,
        json={"master_ids": [other.json()["id"]]},
    )
    assert assigned.status_code == 200, assigned.text

    assert (
        client.post(f"/api/repairs/{repair_id}/print-label", headers=master_headers).status_code
        == 403
    )
    assert client.get(f"/api/repairs/{repair_id}", headers=master_headers).status_code in (403, 404)
