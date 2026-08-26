def test_create_repair_number(client, created_repair):
    assert created_repair["number"].startswith("TV-MSK-2026-")
    assert created_repair["status"] == "Принято"
    assert created_repair["storage_until"] is not None


def test_idempotency(client, operator_headers, city_id):
    payload = {
        "city_id": city_id,
        "client": {"full_name": "Идемпотент", "phone": "+79991112233"},
        "device_type": "ТВ",
    }
    r1 = client.post(
        "/api/repairs", headers={**operator_headers, "Idempotency-Key": "idem-1"}, json=payload
    )
    r2 = client.post(
        "/api/repairs", headers={**operator_headers, "Idempotency-Key": "idem-1"}, json=payload
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


def test_public_page(client, created_repair):
    token = created_repair["public_token"]
    r = client.get(f"/api/public/r/{token}")
    assert r.status_code == 200
    body = r.json()
    # Limited DTO: no internal fields.
    assert "fault_master" not in body
    assert "client_phone" not in body
    assert body["storage_text"]


def test_public_page_not_found(client):
    r = client.get("/api/public/r/does-not-exist")
    assert r.status_code == 404


def test_master_scoped_to_own(client, master_headers, created_repair):
    r = client.get("/api/repairs", headers=master_headers)
    assert r.status_code == 200
    numbers = {x["number"] for x in r.json()}
    # The operator-created repair has no master assigned, so master shouldn't see it.
    assert created_repair["number"] not in numbers


def test_update_status_timeline(client, admin_headers, created_repair):
    r = client.patch(
        f"/api/repairs/{created_repair['id']}",
        headers=admin_headers,
        json={"status": "Диагностика"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "Диагностика"
    types = [e["type"] for e in r.json()["events"]]
    assert "status_change" in types
