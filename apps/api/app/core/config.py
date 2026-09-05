"""Application configuration.

All values come from environment variables (see `.env.example`).
Secrets live only in env — never hardcoded.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    APP_NAME: str = "MSB"
    ENV: str = "dev"  # dev | prod
    API_PREFIX: str = "/api"
    # Публичный адрес фронтенда, куда ведёт QR на бланке (/r/{token}).
    # Для локальной сети укажите IP машины, например http://192.168.8.81:3030
    PUBLIC_BASE_URL: str = "http://localhost:3030"

    # --- Database ---
    # prod: postgresql+asyncpg://user:pass@postgres:5432/msb
    # dev/test (sandbox): sqlite+aiosqlite:///./msb.db
    DATABASE_URL: str = "sqlite+aiosqlite:///./msb.db"

    # --- Auth / JWT ---
    SECRET_KEY: str = "CHANGE_ME_dev_only_0123456789abcdef0123456789abcdef"
    ACCESS_TOKEN_TTL_MIN: int = 30
    REFRESH_TOKEN_TTL_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:3030", "http://localhost:8085"]

    # --- Storage ---
    # local = filesystem (dev/MVP), s3 = MinIO/S3-compatible (prod).
    STORAGE_MODE: str = "local"
    UPLOAD_DIR: str = "./uploads"
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "msb"

    # --- AI ---
    AI_PROVIDER: str = "openai_compat"  # abstraction key
    AI_API_KEY: str = ""
    AI_BASE_URL: str = ""
    AI_MODEL: str = ""

    # --- SMS gateway ---
    # Реальные значения (URL/логин/пароль/вкл-выкл) настраиваются в админке
    # (Admin → SMS, хранится в БД как Setting["sms_server"]) либо через env.
    #
    # ВАЖНО: здесь намеренно НЕТ боевых логина/пароля. Секреты не должны
    # попадать в исходники и в git-историю — только env или настройки в БД.
    # При пустом URL/логине отправка просто возвращает {"ok": False}.
    SMS_ENABLED: bool = False
    SMS_GATEWAY_URL: str = ""
    SMS_GATEWAY_USERNAME: str = ""
    SMS_GATEWAY_PASSWORD: str = ""
    # Сертификат шлюза может быть самоподписанным — тогда это аналог `curl -k`.
    # Включайте только для доверенной внутренней сети.
    SMS_VERIFY_SSL: bool = True
    SMS_TIMEOUT_SEC: float = 10.0

    # --- Seed admin (first boot) ---
    SEED_ADMIN_EMAIL: str = "admin@msb.local"
    SEED_ADMIN_PASSWORD: str = "admin123"  # только dev; в ENV=prod обязательно заменить
    # Регион развёртывания — Туркменистан (+993).
    SEED_ADMIN_PHONE: str = "+99300000000"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
