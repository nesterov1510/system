"""Фотографии в карточке ремонта: миниатюры, порядок, удаление, понятные ошибки.

Раньше:
  - в сетку карточки подставлялись полные оригиналы (единицы мегабайт) в ячейку
    ~76 px, без `loading="lazy"` — на телефоне это было заметно;
  - порядок фото не был определён (запрос без `order_by`);
  - ошибочно загруженное фото нельзя было убрать;
  - пустая форма загрузки молча редиректила, а ошибка формата приходила сырым
    JSON вроде {"detail":"Недопустимый формат файла: .gif"}.
"""
import io
import uuid
from pathlib import Path, PurePosixPath

import pytest
from PIL import Image

UPLOAD_ROOT = Path("./test_uploads")


@pytest.fixture(autouse=True)
def _clear_web_session(client):
    """Сессионный TestClient общий: не оставляем cookie логина соседним тестам."""
    yield
    client.get("/logout", follow_redirects=False)
    client.cookies.clear()


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def repair_id(client, operator_headers, city_id):
    """Свежий ремонт на каждый тест — без исполнителя."""
    r = client.post(
        "/api/repairs",
        headers={**operator_headers, "Idempotency-Key": f"photo-{uuid.uuid4().hex[:8]}"},
        json={
            "city_id": city_id,
            "client": {
                "full_name": "Фото Тест",
                "phone": "+993 61 509933",
                "consent_pdn": True,
            },
            "device_type": "Телевизоры",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client, headers, repair_id, filename="photo.png", data=None):
    return client.post(
        f"/api/repairs/{repair_id}/photos",
        headers=headers,
        files={
            "file": (
                filename,
                data if data is not None else _png(900, 700),
                "image/png",
            )
        },
    )


def _photo_dir(repair_id) -> Path:
    return UPLOAD_ROOT / "repairs" / repair_id


# --------------------------------------------------------------------------
# Миниатюры
# --------------------------------------------------------------------------
def test_upload_creates_thumbnail(client, admin_headers, repair_id):
    original = _png(900, 700)
    r = _upload(client, admin_headers, repair_id, data=original)
    assert r.status_code == 201, r.text

    thumbs = list((_photo_dir(repair_id) / "thumbs").glob("*.jpg"))
    assert len(thumbs) == 1, f"миниатюра не создана: {sorted(p.name for p in _photo_dir(repair_id).rglob('*'))}"
    # Миниатюра меньше оригинала и вписывается в лимит.
    assert thumbs[0].stat().st_size < len(original)
    with Image.open(thumbs[0]) as img:
        assert max(img.size) <= 320


def test_thumbnail_survives_unreadable_source(client, admin_headers, repair_id, monkeypatch):
    """Если миниатюру сделать не удалось — фото всё равно загружается.

    Так ведёт себя, например, HEIC без декодера: карточка покажет оригинал.
    """
    from app.routers import repairs as repairs_router

    # Патчим имя в модуле-потребителе: repairs.py импортирует функцию
    # напрямую, поэтому подмена в storage на него бы не подействовала.
    monkeypatch.setattr(repairs_router, "make_thumbnail", lambda data: None)
    r = _upload(client, admin_headers, repair_id, filename="shot.png")
    assert r.status_code == 201, r.text
    assert not (_photo_dir(repair_id) / "thumbs").exists()


# --------------------------------------------------------------------------
# Удаление
# --------------------------------------------------------------------------
def test_delete_photo_removes_row_and_files(client, admin_headers, repair_id):
    up = _upload(client, admin_headers, repair_id)
    assert up.status_code == 201, up.text
    photo_id = up.json()["id"]

    d = client.delete(
        f"/api/repairs/{repair_id}/photos/{photo_id}", headers=admin_headers
    )
    assert d.status_code == 200, d.text
    assert d.json() == {"ok": True}

    listing = client.get(f"/api/repairs/{repair_id}/photos", headers=admin_headers)
    assert listing.json() == []
    # Файлы сняты с диска: ни оригинала, ни миниатюры.
    assert not list(_photo_dir(repair_id).rglob("*.jpg"))
    assert not list(_photo_dir(repair_id).rglob("*.png"))


def test_delete_photo_of_foreign_repair_is_forbidden(
    client, master_headers, repair_id, admin_headers
):
    """Ремонт без исполнителя: мастер его видит, но менять не может."""
    up = _upload(client, admin_headers, repair_id)
    assert up.status_code == 201, up.text

    d = client.delete(
        f"/api/repairs/{repair_id}/photos/{up.json()['id']}", headers=master_headers
    )
    assert d.status_code == 403, d.text
    # Фото осталось на месте.
    listing = client.get(f"/api/repairs/{repair_id}/photos", headers=admin_headers)
    assert len(listing.json()) == 1


def test_delete_missing_photo_is_404(client, admin_headers, repair_id):
    r = client.delete(
        f"/api/repairs/{repair_id}/photos/{uuid.uuid4()}", headers=admin_headers
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------
# Понятные ошибки в веб-интерфейсе
# --------------------------------------------------------------------------
def _login_webui(client):
    r = client.post(
        "/login",
        data={"email": "admin@msb.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def test_webui_empty_upload_reports_error(client, repair_id):
    _login_webui(client)
    r = client.post(f"/repairs/{repair_id}/photos", data={}, follow_redirects=False)
    assert r.status_code == 400, r.status_code
    assert "Выберите файл" in r.text
    # Ничего не загрузилось.
    assert not _photo_dir(repair_id).exists() or not list(_photo_dir(repair_id).iterdir())


def test_webui_bad_format_shows_message_not_json(client, repair_id):
    _login_webui(client)
    r = client.post(
        f"/repairs/{repair_id}/photos",
        files={"file": ("anim.gif", b"GIF89a", "image/gif")},
        follow_redirects=False,
    )
    assert r.status_code == 400, r.status_code
    assert "Недопустимый формат" in r.text
    assert "detail" not in r.text, "мастеру показался сырой JSON вместо сообщения"


def test_webui_delete_route(client, admin_headers, repair_id):
    up = _upload(client, admin_headers, repair_id)
    assert up.status_code == 201, up.text
    _login_webui(client)

    r = client.post(
        f"/repairs/{repair_id}/photos/{up.json()['id']}/delete",
        follow_redirects=False,
    )
    assert r.status_code == 303, r.status_code
    assert client.get(f"/api/repairs/{repair_id}/photos", headers=admin_headers).json() == []


# --------------------------------------------------------------------------
# Карточка: миниатюры, ленивая загрузка, порядок
# --------------------------------------------------------------------------
def test_card_uses_thumbnails_with_lazy_loading(client, admin_headers, repair_id):
    for _ in range(3):
        assert _upload(client, admin_headers, repair_id, data=_png(800, 600)).status_code == 201

    _login_webui(client)
    card = client.get(f"/repairs/{repair_id}").text

    assert card.count('loading="lazy"') == 3, "фото грузятся без loading=lazy"
    assert "/thumbs/" in card, "в сетке должны быть миниатюры, а не оригиналы"
    assert card.count("rcard-photo") >= 3
    # Клик по фото открывает оригинал.
    assert 'target="_blank"' in card


def test_card_orders_photos_by_created_at(client, admin_headers, repair_id):
    """Порядок фото в карточке — по created_at, а не как строки легли в БД.

    Загружаем три фото, а затем проставляем им created_at в обратном порядке.
    Без order_by запрос вернул бы их в порядке вставки, и расхождение стало бы
    видно — именно так тест ловит отсутствие сортировки.
    """
    import asyncio
    import re
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from app.db.models import RepairPhoto
    from app.db.session import async_session_factory

    uploaded = []
    for _ in range(3):
        r = _upload(client, admin_headers, repair_id)
        assert r.status_code == 201, r.text
        # url → /media/repairs/<id>/<stem>.png; в сетке карточки лежит
        # миниатюра того же stem: /media/repairs/<id>/thumbs/<stem>.jpg
        stem = PurePosixPath(r.json()["url"]).stem
        uploaded.append(f"/media/repairs/{repair_id}/thumbs/{stem}.jpg")

    async def _reverse_dates():
        async with async_session_factory() as db:
            rows = (await db.execute(
                select(RepairPhoto).where(RepairPhoto.repair_id == uuid.UUID(repair_id))
            )).scalars().all()
            base = datetime(2026, 1, 1, 12, 0, 0)
            # Последнее загруженное делаем самым ранним по created_at.
            for offset, photo in enumerate(reversed(rows)):
                photo.created_at = base + timedelta(minutes=offset)
            await db.commit()

    asyncio.run(_reverse_dates())

    _login_webui(client)
    card = client.get(f"/repairs/{repair_id}").text
    got = re.findall(r'<img src="(/media/[^"]+)"', card)

    assert len(got) == 3, f"ожидалось 3 фото в карточке, найдено {len(got)}"
    assert got == list(reversed(uploaded)), (
        "карточка должна показывать фото по created_at, а не в порядке вставки:\n"
        f"  в разметке: {got}\n"
        f"  ожидалось:  {list(reversed(uploaded))}"
    )
