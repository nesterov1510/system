"""Классификация нарушений уникальности (`IntegrityError`) по имени ограничения.

Зачем: приёмка техники повторяет попытку, когда два оператора одновременно
создают ремонт и счётчик номера выдаёт одно и то же значение. Раньше retry-цикл
считал конфликтом номера ЛЮБУЮ `IntegrityError`, поэтому настоящая причина
(например, клиент с таким телефоном уже есть, но мягко удалён и невидим для
поиска) пряталась за сообщением «Не удалось выделить номер ремонта — приёмку
пытаются оформить одновременно», а пять повторов падали с одной и той же ошибкой.

Имя ограничения берётся из драйвера:
* asyncpg (PostgreSQL) — `exc.orig.constraint_name`;
* aiosqlite (SQLite, локальная разработка и тесты) — только текст сообщения
  (`UNIQUE constraint failed: clients.phone_norm`).
"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError

# Конфликт последовательного номера ремонта — можно повторить с новым номером.
NUMBER = "number"
# Конфликт уникального телефона клиента — повторять бессмысленно, надо
# разбираться с карточкой клиента (см. `_persist_repair`).
CLIENT_PHONE = "client_phone"
# Всё остальное — повтор не поможет, ошибку надо показывать честно.
OTHER = "other"

_NUMBER_MARKERS = ("ix_repairs_number", "repairs.number")
_CLIENT_PHONE_MARKERS = ("ix_clients_phone_norm", "clients.phone_norm")


def constraint_name(exc: BaseException) -> str:
    """Имя нарушенного ограничения (или текст ошибки, если драйвер его не дал)."""
    orig = getattr(exc, "orig", None) or exc
    name = getattr(orig, "constraint_name", None)
    if name:
        return str(name)
    # SQLAlchemy оборачивает сообщение драйвера в str(exc): «... [SQL: INSERT
    # INTO clients ...]» — по нему тоже можно опознать таблицу/колонку.
    return f"{orig} {exc}".lower()


def classify(exc: BaseException) -> str:
    """Определить, что именно не удалось вставить: `NUMBER` | `CLIENT_PHONE` | `OTHER`."""
    if not isinstance(exc, IntegrityError):
        return OTHER
    where = constraint_name(exc).lower()
    # Телефон клиента проверяем первым: в сообщении SQLAlchemy рядом с именем
    # ограничения бывает и текст SQL (`INSERT INTO clients ...`), а номер
    # ремонта вставляется в той же транзакции.
    if any(marker in where for marker in _CLIENT_PHONE_MARKERS):
        return CLIENT_PHONE
    if any(marker in where for marker in _NUMBER_MARKERS):
        return NUMBER
    return OTHER
