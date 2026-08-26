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
        json={"text": "Проверка #TV-MSK-00001"},
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
