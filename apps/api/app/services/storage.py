"""File storage abstraction: local filesystem (MVP) or S3/MinIO (prod).

Интерфейс: `save_object(bytes, key)`, `public_url(key)`, `remove_objects(keys)`.

`STORAGE_MODE=s3` в этой сборке не подключён: вместо `ModuleNotFoundError`
(модуля `storage_s3` в репозитории нет) отдаём внятную ошибку с указанием,
что нужно сделать.
"""
import logging
import os
from pathlib import Path

from app.core.config import settings

log = logging.getLogger("msb.storage")

# Allowed image extensions for photo uploads.
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


class StorageNotConfigured(RuntimeError):
    """Выбран неподдерживаемый в этой сборке режим хранения."""


def _ensure_upload_dir() -> Path:
    p = Path(settings.UPLOAD_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def validate_extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Недопустимый формат файла: {ext or '—'}")
    return ext


def _guard_s3() -> None:
    if settings.STORAGE_MODE == "s3":
        raise StorageNotConfigured(
            "STORAGE_MODE=s3 не подключён в этой сборке: модуль storage_s3 "
            "не реализован. Используйте STORAGE_MODE=local либо добавьте "
            "интеграцию с boto3/MinIO в app/services/storage_s3.py."
        )


async def save_local(data: bytes, object_key: str) -> None:
    root = _ensure_upload_dir()
    target = root / object_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


async def save_object(data: bytes, object_key: str) -> None:
    _guard_s3()
    await save_local(data, object_key)


def public_url(object_key: str) -> str:
    if settings.STORAGE_MODE == "s3":
        return f"{settings.S3_ENDPOINT}/{settings.S3_BUCKET}/{object_key}"
    return f"/media/{object_key}"


def object_key_for(repair_id: str, filename: str) -> str:
    ext = validate_extension(filename)
    import uuid

    return f"repairs/{repair_id}/{uuid.uuid4().hex}{ext}"


def remove_objects(object_keys: list[str]) -> int:
    """Удалить файлы с диска. Возвращает число реально удалённых.

    Ошибка удаления одного файла не прерывает остальные: записи в БД к этому
    моменту уже удалены, и «осиротевший» файл не должен ломать запрос.
    """
    if settings.STORAGE_MODE != "local" or not object_keys:
        return 0
    root = Path(settings.UPLOAD_DIR).resolve()
    removed = 0
    for key in object_keys:
        # Защита от выхода за пределы каталога загрузок (path traversal).
        target = (root / key).resolve()
        if not str(target).startswith(str(root) + os.sep):
            log.warning("skip suspicious object_key: %s", key)
            continue
        try:
            if target.is_file():
                target.unlink()
                removed += 1
        except OSError as exc:
            log.warning("failed to remove %s: %s", target, exc)
        # Пустой каталог ремонта тоже подчищаем.
        try:
            parent = target.parent
            if parent != root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
    return removed
