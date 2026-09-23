"""Экспорт/импорт данных (msb_backup.zip): формат, права, идемпотентность."""
import io
import json
import zipfile

import pytest

from app.services import backup as backup_svc


@pytest.fixture(autouse=True)
def _clear_web_session(client):
    yield
    client.get("/logout", follow_redirects=False)
    client.cookies.clear()


def _login(client, email="admin@msb.local", password="admin123"):
    r = client.post(
        "/login",
        data={"email": email, "password": password, "next_url": "/repairs"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return r.cookies


def _unzip(content: bytes) -> tuple[dict, dict]:
    zf = zipfile.ZipFile(io.BytesIO(content))
    names = zf.namelist()
    assert "meta.json" in names
    assert "msb_export.json" in names
    meta = json.loads(zf.read("meta.json"))
    data = json.loads(zf.read("msb_export.json"))
    return meta, data


# --------------------------------------------------------------------------
# Чистые функции формата
# --------------------------------------------------------------------------
def test_cents_and_dates_roundtrip():
    assert backup_svc.to_cents(500) == 50000
    assert backup_svc.to_cents("12.5") == 1250
    assert backup_svc.from_cents(50000) == 500.0
    assert backup_svc.to_cents(None) is None
    assert backup_svc.fmt_dt(backup_svc.parse_dt("2026-01-01 10:00:00")) == "2026-01-01 10:00:00"
    assert backup_svc.parse_dt("2026-01-02T12:00:00Z").hour == 12
    assert backup_svc.parse_dt("мусор") is None
    assert backup_svc.parse_date("2026-04-01").month == 4


def test_equipment_and_condition_mapping():
    codes, other = backup_svc.equipment_out({"Пульт": True, "Сумка": True, "Ножки": False})
    assert codes == ["remote"] and other == "Сумка"
    codes, other = backup_svc.equipment_out({"items": ["Пульт", "Шнур питания"]})
    assert codes == ["remote", "power_cable"] and other == ""
    comp = backup_svc.equipment_in({"equipment_json": '["remote"]', "equipment_other": "Сумка, Кабель HDMI"})
    assert comp == {"Пульт": True, "Сумка": True, "Кабель HDMI": True}
    # старая база: complectation вместо equipment_json
    # наш экспорт: словарь берётся дословно (формат в БД не меняется)
    comp = backup_svc.equipment_in({"complectation": {"items": ["Пульт"]}})
    assert comp == {"items": ["Пульт"]}
    comp = backup_svc.equipment_in({"complectation": ["remote", "Сумка"]})
    assert comp == {"Пульт": True, "Сумка": True}
    codes, other = backup_svc.condition_out("Царапины на корпусе; трещина")
    assert codes == ["body_scratches"] and other == "трещина"
    assert backup_svc.condition_in({"condition_json": '["body_scratches"]', "condition_other": "трещина"}) == (
        "Царапины на корпусе; трещина"
    )


def test_warranty_days():
    assert backup_svc.warranty_days("90 дней") == 90
    assert backup_svc.warranty_days("3 aý") == 90
    assert backup_svc.warranty_days("1 год") == 365
    assert backup_svc.warranty_days(None) is None


def test_read_backup_file_accepts_zip_json_and_rejects_garbage():
    payload = {"version": "1.0", "tables": {"clients": []}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("meta.json", json.dumps({"x": 1}))
        zf.writestr("data.json", json.dumps(payload))
    got, meta, media = backup_svc.read_backup_file(buf.getvalue())
    assert got["tables"] == {"clients": []} and meta == {"x": 1} and media == {}

    got, _, _ = backup_svc.read_backup_file(json.dumps(payload).encode())
    assert got["tables"] == {"clients": []}
    # «плоский» JSON без tables
    got, _, _ = backup_svc.read_backup_file(json.dumps({"clients": [], "repairs": []}).encode())
    assert "clients" in got["tables"]

    with pytest.raises(backup_svc.ImportError_):
        backup_svc.read_backup_file(b"not json at all")
    with pytest.raises(backup_svc.ImportError_):
        backup_svc.read_backup_file(b"")


# --------------------------------------------------------------------------
# API: экспорт
# --------------------------------------------------------------------------
def test_export_zip_structure(client, admin_headers, created_repair):
    r = client.get("/api/admin/backup/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")
    assert "msb_backup_" in r.headers["content-disposition"]
    meta, data = _unzip(r.content)

    assert meta["format"] == "msb_backup"
    assert meta["record_count"] == sum(meta["tables"].values())
    assert meta["exported_at"] == data["exported_at"]
    assert data["version"] == "1.0"
    tables = data["tables"]
    for name in (
        "clients", "repairs", "repair_masters", "repair_parts", "repair_history",
        "repair_number_aliases", "donor_units", "donor_parts", "app_settings",
        "sms_log", "print_log",
    ):
        assert name in tables, name

    rep = next(x for x in tables["repairs"] if x["number"] == created_repair["number"])
    assert rep["category"] == created_repair["device_type"]
    assert rep["serial_number"] == created_repair.get("serial")
    assert json.loads(rep["equipment_json"]) == ["remote", "power_cable", "legs"]
    assert isinstance(rep["price_final_cents"], (int, type(None)))
    assert rep["accepted_by_name"]
    assert "T" not in (rep["created_at"] or "")  # формат 'YYYY-MM-DD HH:MM:SS'
    cl = next(x for x in tables["clients"] if x["id"] == rep["client_id"])
    assert cl["name"] == cl["full_name"] == "Тест Тестов"
    assert cl["phone_norm"]
    hist = [h for h in tables["repair_history"] if h["repair_id"] == rep["id"]]
    assert hist and hist[0]["event_type"] == "status_change"
    assert json.loads(hist[0]["details_json"])
    st = next(s for s in tables["app_settings"] if s["key"] == "currency")
    assert json.loads(st["value_json"])["code"] == "TMT"


def test_export_json_format_and_preview(client, admin_headers):
    r = client.get("/api/admin/backup/export?format=json", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "1.0" and "tables" in data
    p = client.get("/api/admin/backup/preview", headers=admin_headers)
    assert p.status_code == 200
    assert p.json()["tables"]["repairs"] == len(data["tables"]["repairs"])


def test_export_import_admin_only(client, operator_headers, master_headers):
    for h in (operator_headers, master_headers):
        assert client.get("/api/admin/backup/export", headers=h).status_code == 403
        r = client.post(
            "/api/admin/backup/import", headers=h,
            files={"file": ("x.json", b'{"tables":{}}', "application/json")},
        )
        assert r.status_code == 403
    assert client.get("/api/admin/backup/export").status_code == 401


# --------------------------------------------------------------------------
# Импорт: файл по шаблону обмена (старые id, копейки, старые названия полей)
# --------------------------------------------------------------------------
def _template_payload():
    return {
        "version": "1.0",
        "exported_at": "2026-09-23 12:00:00",
        "tables": {
            "clients": [
                {
                    "id": "c-100",
                    "name": "Ахмед Ахмедов",
                    "phone": "+99361000000",
                    "phone_norm": "99361000000",
                    "extra_phones_json": "[]",
                    "created_at": "2026-01-01 10:00:00",
                    "updated_at": "2026-01-01 10:00:00",
                    "deleted_at": None,
                }
            ],
            "repairs": [
                {
                    "id": "r-200",
                    "number": "tv-btrx-260101-ABCD1234",
                    "public_token": "a1b2c3d4e5f6a1b2c3d4e5f6",
                    "client_id": "c-100",
                    "device_type": "Телевизоры",
                    "brand": "SAMSUNG",
                    "model": "QE55Q70",
                    "serial": "SN12345",
                    "fault_client": "Не включается",
                    "work_done": "Замена блока питания",
                    "diagnosis": "Сгорел ШИМ-контроллер",
                    "equipment_json": "[\"remote\"]",
                    "equipment_other": "Сумка",
                    "condition_json": "[\"body_scratches\"]",
                    "condition_other": "",
                    "photos_json": "[]",
                    "is_delivery": 1,
                    "delivery_district": "Парахат 3/2",
                    "delivery_person": "Курьер",
                    "delivery_phone": "+99361111111",
                    "delivery_fee_cents": 1250,
                    "accepted_by_id": 1,
                    "accepted_by_name": "Админ",
                    "status": "Выдано",
                    "price_final_cents": 50000,
                    "price_max_cents": 60000,
                    "paid_cents": 50000,
                    "payment_mark": 1,
                    "master_payout_cents": 15000,
                    "warranty_start": "2026-01-01",
                    "warranty_until": "2026-04-01",
                    "responsible_master_id": 7,
                    "issued_at": "2026-01-02 12:00:00",
                    "finished_at": "2026-01-01 18:00:00",
                    "created_at": "2026-01-01 10:00:00",
                    "updated_at": "2026-01-02 12:00:00",
                    "deleted_at": None,
                }
            ],
            "repair_masters": [
                {
                    "repair_id": "r-200",
                    "user_id": 7,
                    "display_name": "Мастер Ахмед",
                    "assignment_role": "master",
                    "reward_cents": 15000,
                },
                {
                    "repair_id": "r-200",
                    "user_id": 8,
                    "display_name": "Помощник Мерген",
                    "assignment_role": "assistant",
                    "reward_cents": 0,
                },
            ],
            "repair_parts": [
                {
                    "id": "p-10",
                    "repair_id": "r-200",
                    "name": "ШИМ контроллер",
                    "quantity": 1,
                    "unit_cost_cents": 3500,
                    "created_at": "2026-01-01 11:00:00",
                }
            ],
            "repair_history": [
                {
                    "id": "h-100",
                    "repair_id": "r-200",
                    "event_type": "status_change",
                    "actor_user_id": 7,
                    "actor_name": "Мастер Ахмед",
                    "comment": "Ремонт завершён",
                    "details_json": "{}",
                    "created_at": "2026-01-01 18:00:00",
                }
            ],
            "repair_number_aliases": [
                {"old_number": "MSB-00123", "repair_id": "r-200"}
            ],
            "donor_units": [
                {
                    "id": "d-1",
                    "brand": "LG",
                    "model": "42LN540V",
                    "serial_number": "SN999",
                    "board_number": "EAX64891306",
                    "comment": "На разбор",
                    "created_at": "2026-01-01 10:00:00",
                    "updated_at": "2026-01-01 10:00:00",
                }
            ],
            "donor_parts": [
                {
                    "id": "dp-1",
                    "donor_id": "d-1",
                    "name": "Материнская плата Main",
                    "quantity": 1,
                    "panel_number": "LC420DUE",
                    "price_cents": 30000,
                    "created_at": "2026-01-01 10:00:00",
                }
            ],
            "app_settings": [
                {"key": "storage_months", "value_json": "{\"months\": 4}"},
                {"key": "ip_control", "value_json": "{\"mode\": \"whitelist\", \"whitelist\": []}"},
            ],
            "sms_log": [
                {
                    "id": "s-1",
                    "repair_id": "r-200",
                    "phone": "+99361000000",
                    "text": "Ваша техника готова",
                    "status": "sent",
                    "created_at": "2026-01-01 18:05:00",
                }
            ],
            "print_log": [
                {"id": "pl-1", "repair_id": "r-200", "kind": "blank", "status": "done",
                 "created_at": "2026-01-01 10:05:00"}
            ],
        },
    }


def _post_import(client, headers, payload, mode="merge", **form):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return client.post(
        "/api/admin/backup/import",
        headers=headers,
        files={"file": ("msb_export.json", body, "application/json")},
        data={"mode": mode, **form},
    )


def test_import_template_file_and_idempotency(client, admin_headers):
    payload = _template_payload()

    dry = _post_import(client, admin_headers, payload, dry_run="1")
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True and dry.json()["tables"]["repairs"] == 1

    r = _post_import(client, admin_headers, payload)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["ok"] is True
    assert rep["tables"]["clients"]["created"] == 1
    assert rep["tables"]["repairs"]["created"] == 1
    assert rep["tables"]["repair_masters"]["created"] == 2
    assert rep["tables"]["repair_parts"]["created"] == 1
    assert rep["tables"]["repair_history"]["created"] == 1
    assert rep["tables"]["sms_log"]["created"] == 1
    assert rep["tables"]["print_log"]["created"] == 1
    assert rep["tables"]["repair_number_aliases"]["created"] == 1
    assert rep["tables"]["donor_units"]["created"] == 1
    assert rep["tables"]["donor_parts"]["created"] == 1
    assert rep["tables"]["payments"]["created"] == 1  # paid_cents → платёж
    # ip_control защищён, storage_months обновлён/создан
    assert rep["tables"]["app_settings"]["skipped"] == 1
    # Неизвестные мастера созданы как сотрудники
    assert any("Мастер Ахмед" in u for u in rep["created_users"])
    assert any("Помощник Мерген" in u for u in rep["created_users"])

    got = client.get("/api/repairs/by-number/tv-btrx-260101-ABCD1234", headers=admin_headers)
    assert got.status_code == 200, got.text
    repair = got.json()
    assert repair["device_type"] == "Телевизоры"
    assert repair["serial"] == "SN12345"
    assert repair["status"] == "Завершён"  # «Выдано» → Завершён + issued_at
    assert repair["issued_at"] is not None
    assert repair["ready_at"] is not None
    assert float(repair["price_final"]) == 500.0
    assert float(repair["price_max"]) == 600.0
    assert float(repair["master_payout"]) == 150.0
    assert repair["paid"] is True
    assert repair["fault_master"] == "Сгорел ШИМ-контроллер"
    assert repair["complectation"] == {"Пульт": True, "Сумка": True}
    assert repair["condition_notes"] == "Царапины на корпусе"
    assert repair["is_delivery"] is True
    assert repair["delivery_district"] == "Парахат 3/2"
    assert repair["warranty_text"] == "90 дней"
    assert repair["master_names"] == ["Мастер Ахмед"]
    assert repair["helper_names"] == ["Помощник Мерген"]
    types = [e["type"] for e in repair["events"]]
    assert "status_change" in types and "notify" in types

    pays = client.get(f"/api/repairs/{repair['id']}/payments", headers=admin_headers)
    assert pays.status_code == 200 and float(pays.json()[0]["amount"]) == 500.0

    parts = client.get(f"/api/repairs/{repair['id']}/parts", headers=admin_headers)
    assert parts.status_code == 200, parts.text
    names = [p["name"] if "name" in p else p.get("part_name") for p in parts.json()]
    assert any(n and "ШИМ" in n for n in names) or len(parts.json()) == 1

    # Повторный импорт того же файла ничего не дублирует.
    r2 = _post_import(client, admin_headers, payload)
    assert r2.status_code == 200, r2.text
    rep2 = r2.json()
    assert rep2["created"] == 0, rep2
    assert rep2["tables"]["repairs"]["updated"] == 1
    assert rep2["created_users"] == []
    got2 = client.get("/api/repairs/by-number/tv-btrx-260101-ABCD1234", headers=admin_headers).json()
    assert len(got2["events"]) == len(repair["events"])
    assert got2["master_names"] == ["Мастер Ахмед"]
    pays2 = client.get(f"/api/repairs/{repair['id']}/payments", headers=admin_headers).json()
    assert len(pays2) == 1

    # Старый номер (alias) ведёт на карточку.
    cookies = _login(client)
    resp = client.get("/repairs/by-number/MSB-00123", cookies=cookies, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith(f"/repairs/{repair['id']}")


def test_import_rejects_bad_file(client, admin_headers):
    r = client.post(
        "/api/admin/backup/import",
        headers=admin_headers,
        files={"file": ("x.zip", b"garbage", "application/zip")},
    )
    assert r.status_code == 400
    r = client.post(
        "/api/admin/backup/import",
        headers=admin_headers,
        files={"file": ("x.json", b'{"foo": 1}', "application/json")},
    )
    assert r.status_code == 400
    assert "tables" in r.json()["detail"]


def test_import_skips_repair_without_client_but_keeps_rest(client, admin_headers):
    payload = {
        "version": "1.0",
        "tables": {
            "clients": [{"id": "c-1", "full_name": "Без телефона", "phone": ""}],
            "repairs": [
                {"id": "r-1", "number": "NOCLIENT-1", "client_id": "c-404", "category": "Мониторы"},
                {"id": "r-2", "client_id": "c-9", "client_phone": "+99365123456",
                 "client_name": "Инлайн Клиент", "category": "Мониторы", "status": "Новый"},
            ],
        },
    }
    r = _post_import(client, admin_headers, payload)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["tables"]["clients"]["skipped"] == 1
    assert rep["tables"]["repairs"]["skipped"] == 1
    assert rep["tables"]["repairs"]["created"] == 1  # клиент взят из самого ремонта
    assert any("c-404" in w for w in rep["warnings"])
    # номер сгенерирован автоматически
    lst = client.get("/api/repairs?q=99365123456", headers=admin_headers)
    assert lst.status_code == 200
    items = lst.json()["items"] if isinstance(lst.json(), dict) else lst.json()
    assert any(i["brand"] is None and i["device_type"] == "Мониторы" for i in items)


# --------------------------------------------------------------------------
# Round-trip: экспорт → импорт в ту же базу ничего не меняет
# --------------------------------------------------------------------------
def test_export_then_import_is_noop(client, admin_headers, created_repair):
    r = client.get("/api/admin/backup/export", headers=admin_headers)
    _, data = _unzip(r.content)
    before = client.get("/api/admin/backup/preview", headers=admin_headers).json()["tables"]

    imp = client.post(
        "/api/admin/backup/import",
        headers=admin_headers,
        files={"file": ("msb_backup.zip", r.content, "application/zip")},
        data={"mode": "merge"},
    )
    assert imp.status_code == 200, imp.text
    rep = imp.json()
    assert rep["ok"] and rep["created"] == 0, rep
    after = client.get("/api/admin/backup/preview", headers=admin_headers).json()["tables"]
    assert before == after

    got = client.get(f"/api/repairs/{created_repair['id']}", headers=admin_headers).json()
    assert got["number"] == created_repair["number"]
    assert got["complectation"] == created_repair["complectation"]


# --------------------------------------------------------------------------
# Веб-интерфейс: вкладка «Данные»
# --------------------------------------------------------------------------
def test_web_backup_page_export_and_import(client, admin_headers):
    cookies = _login(client)
    page = client.get("/admin/settings?section=backup", cookies=cookies)
    assert page.status_code == 200
    assert "msb_backup.zip" in page.text
    assert 'action="/admin/settings/backup/import"' in page.text
    assert "/admin/settings/backup/export" in page.text
    # ссылка на вкладку есть и в остальных разделах
    general = client.get("/admin/settings?section=general", cookies=cookies)
    assert "section=backup" in general.text

    dl = client.get("/admin/settings/backup/export", cookies=cookies)
    assert dl.status_code == 200
    meta, data = _unzip(dl.content)
    assert meta["exported_by"] == "admin@msb.local"

    payload = _template_payload()
    payload["tables"]["clients"][0]["id"] = "c-777"
    payload["tables"]["clients"][0]["phone"] = "+99362777777"
    payload["tables"]["clients"][0]["phone_norm"] = "99362777777"
    payload["tables"]["repairs"][0].update({"id": "r-777", "client_id": "c-777",
                                            "number": "WEB-IMPORT-1", "public_token": "tok777"})
    for row in payload["tables"]["repair_masters"] + payload["tables"]["repair_parts"] + \
            payload["tables"]["repair_history"] + payload["tables"]["sms_log"] + payload["tables"]["print_log"]:
        row["repair_id"] = "r-777"
    payload["tables"]["repair_number_aliases"] = []
    body = json.dumps(payload, ensure_ascii=False).encode()
    res = client.post(
        "/admin/settings/backup/import",
        cookies=cookies,
        files={"file": ("msb_export.json", body, "application/json")},
        data={"mode": "merge"},
    )
    assert res.status_code == 200, res.text[:500]
    assert "Импорт выполнен" in res.text
    assert "WEB-IMPORT-1" in client.get("/api/repairs/by-number/WEB-IMPORT-1", headers=admin_headers).text

    # режим «заменить» без подтверждения отклоняется
    res = client.post(
        "/admin/settings/backup/import",
        cookies=cookies,
        files={"file": ("msb_export.json", body, "application/json")},
        data={"mode": "replace"},
    )
    assert res.status_code == 400
    assert "ЗАМЕНИТЬ" in res.text


def test_web_backup_requires_admin(client):
    cookies = _login(client, "operator@msb.local", "operator123")
    assert client.get("/admin/settings?section=backup", cookies=cookies).status_code == 403
    assert client.get("/admin/settings/backup/export", cookies=cookies).status_code == 403
    client.cookies.clear()
    r = client.get("/admin/settings/backup/export", follow_redirects=False)
    assert r.status_code == 303


# --------------------------------------------------------------------------
# Режим «заменить»: восстановление из собственной копии сохраняет всё, включая id
# --------------------------------------------------------------------------
def test_replace_mode_restores_own_backup(client, admin_headers, created_repair):
    before = client.get("/api/admin/backup/preview", headers=admin_headers).json()["tables"]
    dump = client.get("/api/admin/backup/export?media=1", headers=admin_headers)
    assert dump.status_code == 200
    _, data = _unzip(dump.content)
    repair_ids = {r["id"] for r in data["tables"]["repairs"]}
    assert created_repair["id"] in repair_ids

    imp = client.post(
        "/api/admin/backup/import",
        headers=admin_headers,
        files={"file": ("msb_backup.zip", dump.content, "application/zip")},
        data={"mode": "replace"},
    )
    assert imp.status_code == 200, imp.text
    rep = imp.json()
    assert rep["ok"] and rep["mode"] == "replace"
    assert rep["tables"]["repairs"]["created"] == before["repairs"]
    assert rep["tables"]["clients"]["created"] == before["clients"]

    after = client.get("/api/admin/backup/preview", headers=admin_headers).json()["tables"]
    for name in ("clients", "repairs", "repair_masters", "repair_parts", "repair_history",
                 "payments", "donor_units", "donor_parts", "sms_log", "users"):
        assert after[name] == before[name], name

    got = client.get(f"/api/repairs/{created_repair['id']}", headers=admin_headers)
    assert got.status_code == 200, got.text
    assert got.json()["number"] == created_repair["number"]
    assert got.json()["public_token"] == created_repair["public_token"]


# --------------------------------------------------------------------------
# Грязные выгрузки старых баз: скаляры вместо JSON-списков, словари вместо списков
# --------------------------------------------------------------------------
def test_jload_ignores_scalars():
    assert backup_svc.jload(0, []) == []
    assert backup_svc.jload("0", []) == []
    assert backup_svc.jload("null", []) == []
    assert backup_svc.jload("true", {}) == {}
    assert backup_svc.jload(5, None) is None
    assert backup_svc.jlist(0) == []
    assert backup_svc.jlist('{"remote": 1, "box": 0}') == ["remote"]
    assert backup_svc.jlist('["a"]') == ["a"]


def test_import_tolerates_scalar_json_fields_and_dict_tables(client, admin_headers):
    payload = {
        "version": "1.0",
        "tables": {
            # словарь {id: запись} вместо списка
            "clients": {
                "c-500": {"full_name": "Словарный Клиент", "phone": "+99363500500",
                          "extra_phones_json": 0},
            },
            "repairs": [
                {
                    "id": "r-500", "number": "DIRTY-500", "client_id": "c-500",
                    "category": "Телевизоры",
                    "equipment_json": 0, "condition_json": "0", "photos_json": 1,
                    "is_delivery": "0", "status": "Готово к выдаче",
                    "price_final_cents": "12000", "accepted_by_id": 0,
                    "created_at": "2026-02-02 10:00:00",
                }
            ],
            "repair_history": {"rows": [
                {"id": 1, "repair_id": "r-500", "event_type": "comment",
                 "comment": "Из старой базы", "details_json": 0,
                 "created_at": "2026-02-02 11:00:00"},
            ]},
            "app_settings": [
                {"key": "brand", "value_json": "\"MSB\""},
            ],
            "users": [
                # active=0: тесты делят одну БД, лишний активный оператор
                # сбил бы тесты чата, которые берут «первого оператора».
                {"id": 3, "name": "Старый Оператор", "email": "old-op@msb.local",
                 "roles": 0, "permissions": "null", "role": "operator", "active": 0},
            ],
        },
    }
    r = _post_import(client, admin_headers, payload)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["ok"], rep
    assert rep["tables"]["clients"]["created"] == 1
    assert rep["tables"]["repairs"]["created"] == 1
    assert rep["tables"]["repair_history"]["created"] == 1
    assert rep["tables"]["users"]["created"] == 1
    got = client.get("/api/repairs/by-number/DIRTY-500", headers=admin_headers).json()
    assert got["status"] == "Завершён" and got["ready_at"]
    assert float(got["price_final"]) == 120.0
    assert got["complectation"] is None
    assert any(e["type"] == "comment" for e in got["events"])


# --------------------------------------------------------------------------
# Реальная выгрузка старой базы: docs/msb_export_20260923_173848.json
# --------------------------------------------------------------------------
def test_import_real_legacy_export_from_docs(client, admin_headers):
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[3] / "docs" / "msb_export_20260923_173848.json"
    data = path.read_bytes()
    # Тесты делят одну БД: запомним настройки SMS, чтобы вернуть их после импорта.
    sms_before = client.get("/api/admin/sms", headers=admin_headers).json()
    r = client.post(
        "/api/admin/backup/import",
        headers=admin_headers,
        files={"file": (path.name, data, "application/json")},
        data={"mode": "merge"},
    )
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["ok"], rep
    assert rep["tables"]["clients"]["created"] == 1
    assert rep["tables"]["repairs"]["created"] == 1
    assert rep["tables"]["repair_masters"]["created"] == 2
    assert rep["tables"]["app_settings"]["created"] + rep["tables"]["app_settings"]["updated"] == 3
    # SMS/печать без ремонта попадают в журнал аудита, а не теряются
    assert rep["tables"]["sms_log"]["created"] == 7
    assert rep["tables"]["print_log"]["created"] == 5
    assert rep["warnings"] == []

    got = client.get("/api/repairs/by-number/tv-btrx-260918-DB0F3E25", headers=admin_headers)
    assert got.status_code == 200, got.text
    repair = got.json()
    assert repair["public_token"] == "8824cadb589444228754ab2cf5a442b120e4e9a3b4de474c8df841d86472a5fe"
    assert repair["device_type"] == "Телевизоры"
    assert repair["serial"] == "FDFDFDFDFD"
    assert repair["complectation"] == {"Только телевизор (без комплекта)": True}
    assert repair["condition_notes"] == "fdsfsfsf"
    assert repair["master_names"] == ["Yoldash SABYROV"]
    assert repair["helper_names"] == ["Merdan Sabyrov"]
    # '2026-09-18T00:15:27+05:00' → UTC
    assert repair["accepted_at"].startswith("2026-09-17T19:15:27")

    # Один человек принял и чинит: оператор + мастер.
    users = client.get("/api/admin/users", headers=admin_headers).json()
    yoldash = next(u for u in users if u["name"] == "Yoldash SABYROV")
    assert yoldash["active"] is False
    assert set(yoldash.get("roles") or [yoldash["role"]]) >= {"operator", "master"}

    # SMS-шлюз из старой базы применён.
    sms = client.get("/api/admin/sms", headers=admin_headers).json()["server"]
    assert sms["url"] == "https://192.168.5.238/api/3rdparty/v1/messages"
    assert sms["username"] == "56FNPL"
    assert sms["enabled"] is True

    audit = client.get("/api/admin/audit?action=sms.sent", headers=admin_headers).json()
    assert sum(1 for a in audit if (a["meta"] or {}).get("imported")) == 7

    # Повторно — ничего не дублируется.
    r2 = client.post(
        "/api/admin/backup/import",
        headers=admin_headers,
        files={"file": (path.name, data, "application/json")},
        data={"mode": "merge"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["created"] == 0, r2.json()

    # Экспорт после импорта содержит те же записи журнала в совместимом виде.
    exp = client.get("/api/admin/backup/export?format=json", headers=admin_headers).json()
    sms_rows = [x for x in exp["tables"]["sms_log"] if x["kind"] == "staff_chat"]
    assert sms_rows and sms_rows[0]["body"] == "Чат [nikita Nesterov]: privte" and sms_rows[0]["ok"] == 1
    prt = [x for x in exp["tables"]["print_log"] if x["target"] == "192.168.8.75:9100"]
    assert len(prt) == 5

    # Вернуть настройки SMS как были (см. test_sms.py).
    restore = {k: v for k, v in sms_before["server"].items() if k != "password"}
    restore["password"] = ""
    rr = client.put("/api/admin/sms", headers=admin_headers, json=restore)
    assert rr.status_code == 200, rr.text
    rr = client.put("/api/admin/sms/templates", headers=admin_headers, json=sms_before["templates"])
    assert rr.status_code == 200, rr.text


# --------------------------------------------------------------------------
# Файл строго по спецификации (docs/EXPORT_FORMAT.md): int-id, минимум полей
# --------------------------------------------------------------------------
def test_import_spec_minimal_external_file(client, admin_headers):
    payload = {
        "version": "1.0",
        "exported_at": "2026-09-23 12:00:00",
        "tables": {
            "clients": [
                {"id": 1, "name": "Внешний Клиент", "phone": "+99364111222",
                 "created_at": "2026-03-01 09:00:00", "is_archived": 0},
                {"id": 2, "full_name": "Архивный Клиент", "phone": "+99364333444",
                 "created_at": "2026-03-01 09:00:00", "is_archived": 1},
            ],
            "repairs": [
                {"id": 10, "number": "TV-2026-001", "category": "Ноутбуки", "brand": "HP",
                 "model": "250 G8", "serial_number": "5CD123", "equipment_json": "[\"charger\"]",
                 "fault_client": "Не заряжается", "work_done": "Замена разъёма",
                 "status": "Принят", "price_final_cents": 25000, "is_paid": 1, "client_id": 1},
                {"id": 11, "number": "TV-2026-002", "category": "Телевизор", "brand": "LG",
                 "serial": "SN-2", "status": "Выдан", "price_final_cents": 0, "is_paid": 0,
                 "client_id": 2, "created_at": "2026-03-02 10:00:00"},
                {"id": 12, "number": "TV-2026-003", "category": "Кофемашина", "status": "Что-то странное",
                 "client_id": 1},
            ],
            "repair_masters": [
                {"repair_id": 10, "user_id": 5, "display_name": "Внешний Мастер", "assignment_role": "master"},
            ],
            "repair_parts": [
                {"id": 1, "repair_id": 10, "name": "Разъём питания", "quantity": 2, "unit_cost_cents": 1500},
            ],
            "repair_history": [
                {"id": 1, "repair_id": 10, "event_type": "comment", "comment": "Принят в работу",
                 "created_at": "2026-03-01 09:05:00"},
            ],
            "donor_units": [{"id": 1, "brand": "HP", "model": "255 G7"}],
            "donor_parts": [{"id": 1, "donor_id": 1, "name": "Матрица", "price_cents": 20000}],
            "sms_log": [],
            "print_log": [],
        },
    }
    r = _post_import(client, admin_headers, payload)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["ok"], rep
    assert rep["tables"]["clients"]["created"] == 2
    assert rep["tables"]["repairs"]["created"] == 3
    assert rep["tables"]["repair_parts"]["created"] == 1
    assert rep["tables"]["donor_parts"]["created"] == 1
    assert any("Что-то странное" in w for w in rep["warnings"])

    a = client.get("/api/repairs/by-number/TV-2026-001", headers=admin_headers).json()
    assert a["device_type"] == "Компьютеры"          # «Ноутбуки» → класс MSB
    assert a["status"] == "Новый"                    # «Принят»
    assert a["paid"] is True and float(a["price_final"]) == 250.0
    assert a["serial"] == "5CD123"
    assert a["complectation"] == {"Зарядное устройство": True}
    assert a["master_names"] == ["Внешний Мастер"]

    b = client.get("/api/repairs/by-number/TV-2026-002", headers=admin_headers).json()
    assert b["device_type"] == "Телевизоры" and b["status"] == "Завершён"
    assert b["issued_at"] is not None and b["ready_at"] is not None

    c = client.get("/api/repairs/by-number/TV-2026-003", headers=admin_headers).json()
    assert c["device_type"] == "Другое" and c["status"] == "Новый"

    # Архивный клиент помечен удалённым.
    exp = client.get("/api/admin/backup/export?format=json", headers=admin_headers).json()
    arch = next(x for x in exp["tables"]["clients"] if x["phone_norm"] == "99364333444")
    assert arch["is_archived"] == 1 and arch["deleted_at"]
    live = next(x for x in exp["tables"]["clients"] if x["phone_norm"] == "99364111222")
    assert live["is_archived"] == 0
    exp_a = next(x for x in exp["tables"]["repairs"] if x["number"] == "TV-2026-001")
    assert exp_a["is_paid"] == 1 and exp_a["price_final_cents"] == 25000

    # Повторный импорт — без дублей.
    r2 = _post_import(client, admin_headers, payload)
    assert r2.status_code == 200 and r2.json()["created"] == 0, r2.text


# --------------------------------------------------------------------------
# Отдельный экспорт / импорт учётных записей сотрудников
# --------------------------------------------------------------------------
def _post_users_import(client, headers, payload, **form):
    body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return client.post(
        "/api/admin/backup/users/import",
        headers=headers,
        files={"file": ("msb_users.json", body, "application/json")},
        data=form,
    )


def test_users_export_only_accounts(client, admin_headers):
    r = client.get("/api/admin/backup/users/export", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith('attachment; filename="msb_users_')
    payload = r.json()
    assert payload["kind"] == "users" and payload["version"] == "1.0"
    assert payload["passwords_included"] is True
    assert set(payload["tables"]) == {"users", "cities", "branches"}
    admin = next(u for u in payload["tables"]["users"] if u["email"] == "admin@msb.local")
    assert admin["role"] == "admin" and admin["password_hash"]
    assert "created_at" in admin and "extra_roles_json" in admin

    # Без паролей
    r2 = client.get("/api/admin/backup/users/export?passwords=0", headers=admin_headers)
    p2 = r2.json()
    assert p2["passwords_included"] is False
    assert all(u["password_hash"] is None for u in p2["tables"]["users"])


def test_users_export_forbidden_for_operator(client, operator_headers):
    r = client.get("/api/admin/backup/users/export", headers=operator_headers)
    assert r.status_code == 403
    r = _post_users_import(client, operator_headers, {"tables": {"users": []}})
    assert r.status_code == 403


def test_users_import_roundtrip_and_password_preserved(client, admin_headers):
    # Создаём сотрудника, выгружаем, меняем ему пароль, импортируем обратно —
    # пароль из файла должен восстановиться.
    r = client.post("/api/admin/users", headers=admin_headers, json={
        "name": "Экспортный Мастер", "email": "export.master@msb.local",
        "password": "secret-1", "role": "master", "roles": ["master", "operator"],
        "active": False,
    })
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    exp = client.get("/api/admin/backup/users/export", headers=admin_headers).json()

    client.patch(f"/api/admin/users/{uid}", headers=admin_headers,
                 json={"password": "changed-2", "name": "Переименован", "roles": ["master"]})

    # dry_run — только состав файла
    d = _post_users_import(client, admin_headers, exp, dry_run="1")
    assert d.status_code == 200, d.text
    assert d.json()["dry_run"] is True
    me = next(u for u in d.json()["users"] if u["email"] == "export.master@msb.local")
    assert me["has_password"] is True and me["active"] is False
    check = client.get("/api/admin/users", headers=admin_headers).json()
    assert next(u for u in check if u["id"] == uid)["name"] == "Переименован"  # ничего не изменилось

    r = _post_users_import(client, admin_headers, exp)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["ok"] and rep["tables"]["users"]["created"] == 0
    assert rep["tables"]["users"]["updated"] >= 2 and rep["deactivated"] == []
    u = next(u for u in client.get("/api/admin/users", headers=admin_headers).json() if u["id"] == uid)
    assert u["name"] == "Экспортный Мастер" and u["active"] is False
    assert set(u["roles"]) == {"master", "operator"}
    # Пароль вернулся к secret-1 — но учётка выключена, поэтому включаем и логинимся
    client.patch(f"/api/admin/users/{uid}", headers=admin_headers, json={"active": True})
    login = client.post("/api/auth/login", json={"email": "export.master@msb.local", "password": "secret-1"})
    assert login.status_code == 200, login.text
    # Возвращаем как было (общая БД тестов): выключаем.
    client.patch(f"/api/admin/users/{uid}", headers=admin_headers, json={"active": False})


def test_users_import_plain_list_with_passwords_and_deactivate_missing(client, admin_headers):
    # Простой список, набранный вручную: открытые пароли, роли в верхнем регистре.
    body = json.dumps([
        {"name": "Новый Оператор", "email": "New.Operator@msb.local", "role": "OPERATOR",
         "password": "op-pass-123", "active": 0},
        {"name": "Без Пароля", "email": "nopass@msb.local", "role": "callcenter", "active": 0},
        {"name": "Странная Роль", "email": "weird@msb.local", "role": "director", "active": 0},
    ]).encode("utf-8")
    r = _post_users_import(client, admin_headers, body)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["tables"]["users"]["created"] == 3
    assert any("nopass@msb.local" in x for x in rep["created_users"])
    assert any("director" in w for w in rep["warnings"])
    users = client.get("/api/admin/users", headers=admin_headers).json()
    by_email = {u["email"]: u for u in users}
    assert by_email["new.operator@msb.local"]["role"] == "operator"   # email и роль нормализованы
    assert by_email["weird@msb.local"]["role"] == "operator"
    assert by_email["nopass@msb.local"]["active"] is False

    # Повторный импорт того же — без дублей.
    r2 = _post_users_import(client, admin_headers, body)
    assert r2.json()["tables"]["users"]["created"] == 0

    # deactivate_missing: файл только с админом → все остальные активные выключаются,
    # сам админ (актор) остаётся. Проверяем на копии и сразу восстанавливаем.
    before_active = {u["id"] for u in users if u["active"]}
    exp = client.get("/api/admin/backup/users/export", headers=admin_headers).json()
    only_admin = dict(exp)
    only_admin["tables"] = {"users": [u for u in exp["tables"]["users"] if u["email"] == "admin@msb.local"]}
    r3 = _post_users_import(client, admin_headers, only_admin, deactivate_missing="1")
    assert r3.status_code == 200, r3.text
    rep3 = r3.json()
    assert rep3["mode"] == "sync"
    assert len(rep3["deactivated"]) == len(before_active - {by_email["admin@msb.local"]["id"]})
    after = client.get("/api/admin/users", headers=admin_headers).json()
    assert [u for u in after if u["active"]] and all(u["email"] == "admin@msb.local" for u in after if u["active"])
    # восстановить: полный экспорт с исходными статусами
    r4 = _post_users_import(client, admin_headers, exp)
    assert r4.status_code == 200, r4.text
    restored = {u["id"] for u in client.get("/api/admin/users", headers=admin_headers).json() if u["active"]}
    assert restored == before_active


def test_users_import_from_full_backup_takes_only_users(client, admin_headers):
    full = client.get("/api/admin/backup/export?format=json", headers=admin_headers).json()
    assert full["tables"]["clients"] is not None
    r = _post_users_import(client, admin_headers, full, dry_run="1")
    assert r.status_code == 200, r.text
    assert r.json()["count"] == len(full["tables"]["users"])
    r = _post_users_import(client, admin_headers, full)
    assert r.status_code == 200, r.text
    assert set(k for k, v in r.json()["tables"].items() if v["created"] or v["updated"]) <= {"users", "cities", "branches"}


def test_users_import_rejects_file_without_users(client, admin_headers):
    r = _post_users_import(client, admin_headers, {"version": "1.0", "tables": {"clients": []}})
    assert r.status_code == 400
    assert "users" in r.text
    r = _post_users_import(client, admin_headers, b"not json")
    assert r.status_code == 400


def test_web_users_page_export_and_import(client, admin_headers):
    cookies = _login(client)
    page = client.get("/admin/users", cookies=cookies)
    assert page.status_code == 200
    assert 'href="/admin/users/export"' in page.text
    assert 'action="/admin/users/import"' in page.text

    dl = client.get("/admin/users/export?passwords=0", cookies=cookies)
    assert dl.status_code == 200
    assert dl.headers["content-disposition"].startswith('attachment; filename="msb_users_')
    assert dl.json()["passwords_included"] is False

    body = json.dumps([{"name": "Веб Импорт", "email": "web.import@msb.local", "role": "master", "active": 0}]).encode()
    r = client.post("/admin/users/import", cookies=cookies,
                    files={"file": ("msb_users.json", body, "application/json")})
    assert r.status_code == 200, r.text[:500]
    assert "Импорт учётных записей выполнен" in r.text
    assert "web.import@msb.local" in r.text

    bad = client.post("/admin/users/import", cookies=cookies,
                      files={"file": ("x.json", b"{}", "application/json")})
    assert bad.status_code == 400
    assert "users" in bad.text
