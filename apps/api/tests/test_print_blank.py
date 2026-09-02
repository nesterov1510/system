"""Данные, которые оператор заполняет для печатного бланка.

Проверяем сквозной путь: заполнили в карточке ремонта → попало в PDF.
Соответствие полей бланка (туркменская форма):
  Gürleşilen baha  — цена ремонта
  Aýdylan wagty    — срок ремонта
  Inžiner 1..4     — мастера (их может быть несколько)
  Kemçilik         — неисправности
  Dakylan ...      — установленные запчасти
  Sargalan ...     — заказанные под ремонт запчасти
  Düzedilen ...    — что починили
  Kepillik         — гарантия
"""
import base64

from pypdf import PdfReader


def _pdf_text(client, headers, repair_id: str) -> str:
    r = client.post(f"/api/repairs/{repair_id}/print", headers=headers)
    assert r.status_code == 200, r.text
    pdf = base64.b64decode(r.json()["pdf_base64"])
    with open("/tmp/test_blank.pdf", "wb") as f:
        f.write(pdf)
    return PdfReader("/tmp/test_blank.pdf").pages[0].extract_text()


def _new_repair(client, headers, city_id: str, key: str) -> dict:
    r = client.post(
        "/api/repairs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "city_id": city_id,
            "client": {"full_name": "Бланк Бланков", "phone": "+99361234567"},
            "device_type": "Ноутбук",
            "brand": "Asus",
            "model": "X515",
            "fault_client": "не включается",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_multiple_masters(client, admin_headers, operator_headers, city_id):
    repair = _new_repair(client, operator_headers, city_id, "blank-masters")
    masters = client.get("/api/lookups/masters", headers=admin_headers).json()
    assert masters, "в тестовой базе должен быть хотя бы один мастер"
    ids = [m["id"] for m in masters]

    r = client.patch(
        f"/api/repairs/{repair['id']}", headers=admin_headers, json={"master_ids": ids}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["master_ids"] == ids
    assert body["master_names"] == [m["name"] for m in masters]
    # Первый мастер становится основным (доска, права доступа).
    assert body["master_id"] == ids[0]
    assert body["master_name"] == masters[0]["name"]

    # Список перезаписывается целиком, дубликаты схлопываются.
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=admin_headers,
        json={"master_ids": [ids[0], ids[0]]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["master_ids"] == [ids[0]]

    # Несуществующий мастер — понятная ошибка, а не 500.
    r = client.patch(
        f"/api/repairs/{repair['id']}",
        headers=admin_headers,
        json={"master_ids": ["00000000-0000-0000-0000-000000000001"]},
    )
    assert r.status_code == 404


def test_part_orders_crud(client, admin_headers, operator_headers, city_id):
    repair = _new_repair(client, operator_headers, city_id, "blank-orders")
    rid = repair["id"]

    r = client.post(
        f"/api/repairs/{rid}/part-orders",
        headers=operator_headers,
        json={"name": "Матрица 15.6 FHD", "qty": 2},
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["name"] == "Матрица 15.6 FHD"
    assert order["qty"] == 2
    assert order["ordered_at"] is not None  # дата проставляется сама

    assert len(client.get(f"/api/repairs/{rid}/part-orders", headers=operator_headers).json()) == 1

    r = client.delete(f"/api/repairs/{rid}/part-orders/{order['id']}", headers=operator_headers)
    assert r.status_code == 200
    assert client.get(f"/api/repairs/{rid}/part-orders", headers=operator_headers).json() == []


def test_blank_contains_operator_data(client, admin_headers, operator_headers, city_id):
    repair = _new_repair(client, operator_headers, city_id, "blank-full")
    rid = repair["id"]
    masters = client.get("/api/lookups/masters", headers=admin_headers).json()

    r = client.patch(
        f"/api/repairs/{rid}",
        headers=admin_headers,
        json={
            "master_ids": [m["id"] for m in masters],
            "fault_master": "Не включается\nШумит вентилятор",
            "work_done": "Заменена клавиатура, чистка охлаждения",
            "warranty_text": "3 aý",
            "eta_days": 4,
            "price_final": 1250,
        },
    )
    assert r.status_code == 200, r.text

    part = client.get("/api/parts", headers=admin_headers).json()[0]
    client.post(
        f"/api/repairs/{rid}/parts", headers=admin_headers, json={"part_id": part["id"], "qty": 1}
    )
    client.post(
        f"/api/repairs/{rid}/part-orders",
        headers=admin_headers,
        json={"name": "Шлейф LVDS", "qty": 1},
    )

    text = _pdf_text(client, admin_headers, rid)

    for master in masters:
        assert master["name"] in text, f"мастер {master['name']} не попал в бланк"
    assert "Не включается" in text          # Kemçilik
    assert "Шумит вентилятор" in text
    assert "Заменена клавиатура" in text    # Düzedilen ... görkezmesi
    assert "3 aý" in text                   # Kepillik
    assert "4 gün" in text                  # Aýdylan wagty
    assert "1 250.00" in text               # Gürleşilen baha
    assert part["name"] in text             # Dakylan ätiýaçlyk şaýlary
    assert "Шлейф LVDS" in text             # Sargalan ätiýaçlyk şaýlary


def test_blank_without_data_is_still_printable(client, operator_headers, city_id):
    """Пустой бланк печатается — просто с пустыми линиями под ручку."""
    repair = _new_repair(client, operator_headers, city_id, "blank-empty")
    text = _pdf_text(client, operator_headers, repair["id"])
    assert "Kemçilik" in text
    assert "Kepillik" in text
    assert repair["number"] in text
