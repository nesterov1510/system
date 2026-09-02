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
