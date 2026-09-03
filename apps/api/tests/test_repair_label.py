"""Этикетка 58×38: PDF, QR-ссылка и отдельная конфигурация принтера."""
import base64
import io

import pytest
from pypdf import PdfReader


LABEL_CONFIG = {
    "ip": "192.168.5.238",
    "port": 631,
    "mode": "cups_remote",
    "name": "3B-350B",
    "width_mm": 58,
    "height_mm": 38,
    "media": "Custom.58x38mm",
}


def test_label_printer_config_and_validation(client, admin_headers):
    r = client.put(
        "/api/admin/printer/label",
        headers=admin_headers,
        json=LABEL_CONFIG,
    )
    assert r.status_code == 200, r.text
    assert r.json()["label_printer"] == LABEL_CONFIG

    config = client.get("/api/admin/printer", headers=admin_headers)
    assert config.status_code == 200
    assert config.json()["label_printer"] == LABEL_CONFIG

    # Формат и маршрут нельзя случайно переключить с требуемых 58×38/CUPS.
    normalized = client.put(
        "/api/admin/printer/label",
        headers=admin_headers,
        json={**LABEL_CONFIG, "mode": "agent", "width_mm": 5, "height_mm": 5},
    )
    assert normalized.status_code == 200
    assert normalized.json()["label_printer"] == LABEL_CONFIG


@pytest.mark.parametrize("headers_fixture", ["admin_headers", "operator_headers"])
def test_repair_label_pdf_and_queue(
    request, client, headers_fixture, created_repair
):
    headers = request.getfixturevalue(headers_fixture)
    r = client.post(
        f"/api/repairs/{created_repair['id']}/print-label",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["repair_url"].endswith(f"/repairs/{created_repair['id']}")
    assert "/r/" not in body["repair_url"]  # QR ведёт в закрытую карточку мастера.

    pdf = base64.b64decode(body["pdf_base64"])
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    page = reader.pages[0]
    points_per_mm = 72 / 25.4
    assert float(page.mediabox.width) == pytest.approx(58 * points_per_mm, abs=0.2)
    assert float(page.mediabox.height) == pytest.approx(38 * points_per_mm, abs=0.2)
    assert page["/Resources"].get("/XObject"), "QR-код должен быть встроен как изображение"

    text = page.extract_text()
    assert created_repair["number"] in text
    assert "Тест Тестов" in text
    assert "+79998887766" in text
    assert "Комплектация:" in text
    assert "Пульт" in text
    assert "Шнур питания" in text
    assert "Ножки" in text
    assert "Дефекты:" in text
    assert "Линии на экране" in text
    assert "Царапины" in text
    assert "Скол корпуса" in text

    jobs = client.get(
        "/api/print/jobs?status=queued",
        headers=headers,
    ).json()
    job = next(j for j in jobs if str(j["id"]) == body["job_id"])
    assert job["template_id"] == "repair-label-58x38"
    assert job["payload"]["document_kind"] == "repair_label"
    assert job["payload"]["printer"] == LABEL_CONFIG

    detail = client.get(
        f"/api/repairs/{created_repair['id']}", headers=headers
    ).json()
    assert any(
        event["data"].get("job_id") == body["job_id"]
        and event["data"].get("kind") == "label"
        for event in detail["events"]
        if event.get("data")
    )


def test_unassigned_repair_label_is_forbidden_to_master(
    client, master_headers, created_repair
):
    r = client.post(
        f"/api/repairs/{created_repair['id']}/print-label",
        headers=master_headers,
    )
    assert r.status_code == 403
    queue = client.get("/api/print/jobs", headers=master_headers)
    assert queue.status_code == 403  # очередь содержит PDF с чужими персональными данными


def test_assigned_master_can_queue_label(
    client, operator_headers, master_headers, city_id
):
    master = client.get("/api/auth/me", headers=master_headers).json()
    created = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": "master-label-repair"},
        json={
            "city_id": city_id,
            "client": {
                "full_name": "Клиент назначенного мастера",
                "phone": "+99365000123",
            },
            "device_type": "Телевизоры",
            "brand": "LG",
            "master_id": master["id"],
        },
    )
    assert created.status_code == 201, created.text

    printed = client.post(
        f"/api/repairs/{created.json()['id']}/print-label",
        headers=master_headers,
    )
    assert printed.status_code == 200, printed.text


def test_admin_can_queue_test_label(client, admin_headers):
    r = client.post("/api/admin/printer/label/test", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued"

    config = client.get("/api/admin/printer", headers=admin_headers).json()
    job = next(j for j in config["recent_jobs"] if j["id"] == r.json()["job_id"])
    assert job["template_id"] == "label-test"
    assert job["printer_name"] == "3B-350B"
