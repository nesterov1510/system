def test_list_channels(client, admin_headers):
    r = client.get("/api/chat/channels", headers=admin_headers)
    assert r.status_code == 200
    slugs = {c["slug"] for c in r.json()}
    assert {"obshchiy", "priemka", "mastera", "callcenter"} <= slugs


def test_send_message_with_mention(client, admin_headers, created_repair):
    channels = client.get("/api/chat/channels", headers=admin_headers).json()
    channel_id = channels[0]["id"]
    r = client.post(
        f"/api/chat/channels/{channel_id}/messages",
        headers=admin_headers,
        json={"text": "Проверка #TV-ASG-00001"},
    )
    assert r.status_code == 200
    assert r.json()["repair_ref"] is not None


def test_operator_assigning_master_sends_direct_notice(
    client, admin_headers, operator_headers, master_headers, city_id
):
    # Создаём свой ремонт (оператор), чтобы не конфликтовать с общей фикстурой.
    phone = "+7999" + "7" * 6 + "1"
    new_repair = client.post(
        "/api/repairs",
        headers=operator_headers,
        json={
            "city_id": city_id,
            "client": {"full_name": "Клиент Уведомления", "phone": phone,
                       "consent_pdn": True, "consent_storage": True},
            "device_type": "Телевизоры",
            "brand": "Samsung",
            "model": "UE50",
        },
    )
    assert new_repair.status_code == 201, new_repair.text
    rid = new_repair.json()["id"]

    # Найдём id мастера через список сотрудников (admin может видеть).
    users = client.get("/api/admin/users", headers=admin_headers).json()
    master_id = next(
        u["id"] for u in users if u["role"] == "master" and u["active"]
    )

    # Оператор назначает мастера на ремонт.
    r = client.patch(
        f"/api/repairs/{rid}",
        headers=operator_headers,
        json={"master_ids": [master_id]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["master_id"] == master_id

    # Мастер в своих личных чатах находит диалог с оператором и уведомление.
    chans = client.get("/api/chat/channels", headers=master_headers).json()
    dms = [c for c in chans if c["kind"] == "direct"]
    assert dms, "у мастера должен появиться личный чат с оператором"
    msgs_all = []
    for chan in dms:
        msgs_all += client.get(
            f"/api/chat/channels/{chan['id']}/messages", headers=master_headers
        ).json()
    found = next(
        m for m in msgs_all
        if m.get("repair_preview") and m["repair_preview"]["id"] == rid
    )
    assert "назначил" in found["text"].lower() or "ремонт" in found["text"].lower()
    assert found["repair_preview"]["id"] == rid


def test_stage_counts(client, admin_headers, created_repair):
    r = client.get("/api/repairs/stage-counts", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    for k in ("all", "new", "diag", "work", "done"):
        assert k in body
    assert body["new"] >= 1  # created_repair в «Принято»
    assert body["all"] >= body["new"]


def test_repair_mention_preview_resolves(client, admin_headers, created_repair):
    channels = client.get("/api/chat/channels", headers=admin_headers).json()
    channel_id = channels[0]["id"]
    number = created_repair["number"]
    r = client.post(
        f"/api/chat/channels/{channel_id}/messages",
        headers=admin_headers,
        json={"text": f"Готово #{number}"},
    )
    assert r.json()["repair_preview"]["number"] == number


def test_direct_messaging(client, admin_headers, operator_headers, master_headers):
    # Оператор ищет админа в списке сотрудников и открывает личный чат.
    users = client.get("/api/chat/users", headers=operator_headers).json()
    adm = next(u for u in users if u["role"] == "admin")
    ch = client.post(f"/api/chat/direct/{adm['id']}", headers=operator_headers)
    assert ch.status_code == 200
    chan = ch.json()
    assert chan["kind"] == "direct"
    assert chan["peer"]["id"] == adm["id"]

    # Оператор пишет сообщение.
    msg = client.post(
        f"/api/chat/channels/{chan['id']}/messages",
        headers=operator_headers,
        json={"text": "Привет, админ"},
    )
    assert msg.status_code == 200

    # Админ видит этот личный чат у себя (peer = оператор) и читает сообщение.
    op = client.get("/api/chat/users", headers=admin_headers).json()
    opuser = next(u for u in op if u["role"] == "operator")
    admin_ch = client.get("/api/chat/channels", headers=admin_headers).json()
    dm = [c for c in admin_ch if c["kind"] == "direct" and c.get("peer", {}).get("id") == opuser["id"]]
    assert dm
    msgs = client.get(
        f"/api/chat/channels/{chan['id']}/messages", headers=admin_headers
    ).json()
    assert any(m["text"] == "Привет, админ" for m in msgs)

    # Посторонний мастер не может читать чужой личный чат.
    denied = client.get(
        f"/api/chat/channels/{chan['id']}/messages", headers=master_headers
    )
    assert denied.status_code == 403
    denied_post = client.post(
        f"/api/chat/channels/{chan['id']}/messages",
        headers=master_headers,
        json={"text": "проникновение"},
    )
    assert denied_post.status_code == 403
