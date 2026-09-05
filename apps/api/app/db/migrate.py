"""Лёгкие авто-миграции (проект пока живёт без Alembic).

`Base.metadata.create_all` создаёт недостающие ТАБЛИЦЫ, но не добавляет новые
КОЛОНКИ в уже существующие. Здесь — минимальный «ALTER TABLE ADD COLUMN» для
таких случаев, работает и на SQLite (dev), и на PostgreSQL (prod).

Добавляйте новые колонки в NEW_COLUMNS — при старте API они появятся сами.
"""
import logging

from sqlalchemy import inspect, text

log = logging.getLogger(__name__)

# {таблица: {колонка: SQL-тип}}
NEW_COLUMNS: dict[str, dict[str, str]] = {
    "repairs": {
        "work_done": "TEXT",
        "warranty_text": "VARCHAR(64)",
        "contact2_name": "VARCHAR(255)",
        "contact2_phone": "VARCHAR(32)",
        "is_delivery": "BOOLEAN DEFAULT FALSE",
        "master_payout": "NUMERIC(12, 2)",
        # Ежедневные SMS-напоминания «заберите технику» (см. services/reminders.py).
        "reminder_next_at": "TIMESTAMP",
        "reminder_last_at": "TIMESTAMP",
        "reminder_count": "INTEGER DEFAULT 0",
    },
    "users": {
        "telegram": "VARCHAR(128)",
        "roles": "JSON",
    },
    "chat_channel_members": {
        "last_read_at": "TIMESTAMP",
    },
    "repair_masters": {
        "kind": "VARCHAR(16) DEFAULT 'master'",
    },
    "repair_parts": {
        "is_manual": "BOOLEAN DEFAULT FALSE",
    },
    "equipment": {
        "storage_place": "VARCHAR(255)",
    },
}


def _sync_columns(conn) -> list[str]:
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []

    for table, columns in NEW_COLUMNS.items():
        if table not in existing_tables:
            continue  # таблицу создаст create_all — там колонки уже есть
        present = {c["name"] for c in inspector.get_columns(table)}
        for column, sql_type in columns.items():
            if column in present:
                continue
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}'))
            applied.append(f"{table}.{column}")
    return applied


async def run_migrations(engine) -> list[str]:
    """Добавить недостающие колонки. Возвращает список применённых изменений."""
    async with engine.begin() as conn:
        applied = await conn.run_sync(_sync_columns)
    if applied:
        log.info("Авто-миграция: добавлены колонки %s", ", ".join(applied))
    return applied
