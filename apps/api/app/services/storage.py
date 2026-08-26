"""File storage abstraction: local filesystem (MVP) or S3/MinIO (prod).

Interface: save(bytes, object_key) -> None ; public_url(object_key) -> str.
"""
import os
from pathlib import Path

from app.core.config import settings

# Allowed image extensions for photo uploads.
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def _ensure_upload_dir() -> Path:
    p = Path(settings.UPLOAD_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def validate_extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Недопустимый формат файла: {ext or '—'}")
    return ext


async def save_local(data: bytes, object_key: str) -> None:
    root = _ensure_upload_dir()
    target = root / object_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


async def save_object(data: bytes, object_key: str) -> None:
    if settings.STORAGE_MODE == "s3":
        # Production path: boto3 -> MinIO/S3. Stub keeps the interface stable.
        from app.services.storage_s3 import save_s3  # noqa: F401

        raise NotImplementedError(
            "S3 storage not wired in this build; set STORAGE_MODE=local for MVP."
        )
    await save_local(data, object_key)


def public_url(object_key: str) -> str:
    if settings.STORAGE_MODE == "s3":
        return f"{settings.S3_ENDPOINT}/{settings.S3_BUCKET}/{object_key}"
    return f"/media/{object_key}"


def object_key_for(repair_id: str, filename: str) -> str:
    ext = validate_extension(filename)
    import uuid

    return f"repairs/{repair_id}/{uuid.uuid4().hex}{ext}"
