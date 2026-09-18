"""Порядок блоков на странице — «конструктор» для админа.

Админ нажимает «🧩 Конструктор» и переставляет блоки страницы (стрелками или
перетаскиванием). Порядок сохраняется в `user_page_layouts` **лично ему**:
у другого админа остаётся свой, а у мастера и оператора — раскладка по
умолчанию (им конструктор не показывается).

Блоки описаны здесь, а в шаблонах помечены `data-block="<ключ>"`. Рендер
выставляет каждому блоку `order:` из сохранённого порядка, поэтому HTML
переставлять не нужно — достаточно CSS-порядка в grid/flex-контейнере.
"""
import uuid

from sqlalchemy import select

from app.db.models import UserPageLayout

# Страницы, где работает конструктор: ключ -> [(имя блока, подпись в меню)].
# Имена блоков должны совпадать с data-block в шаблонах.
PAGE_BLOCKS: dict[str, list[tuple[str, str]]] = {
    "repair_card": [
        ("hero", "Шапка: номер и статус"),
        ("passport", "Паспорт"),
        ("fault", "Неисправность и мастера"),
        ("parts", "Запчасти"),
        ("pay", "Касса"),
        ("log", "Лента и фото"),
    ],
    "repairs_list": [
        ("toolbar", "Поиск и фильтры"),
        ("legend", "Легенда подсветки"),
        ("bulk", "Массовые действия"),
        ("table", "Таблица ремонтов"),
        ("pager", "Страницы и итог"),
    ],
    # Колонки таблицы «Все ремонты» — тот же механизм, но порядок применяется
    # перестановкой ячеек (CSS `order` в таблицах не работает). Ключи должны
    # совпадать с data-col в templates/repairs/list.html.
    "repairs_columns": [
        ("bulk", "Отметить"),
        ("date", "📅 Дата"),
        ("device", "📺 Техника"),
        ("accepted", "🧾 Принял"),
        ("fault", "🔧 Причина"),
        ("fixed", "🛠 Что починили"),
        ("sum", "💵 Сумма"),
        ("parts", "🔩 Запчасти"),
        ("client", "👤 Клиент"),
        ("masters", "👷 Мастера"),
        ("payout", "💰 Выплата"),
        ("total", "🏁 Итог"),
        ("actions", "⚡ Действия"),
    ],
}


def block_keys(page: str) -> list[str]:
    """Все блоки страницы в порядке по умолчанию."""
    return [key for key, _label in PAGE_BLOCKS.get(page, [])]


def block_labels(page: str) -> dict[str, str]:
    return dict(PAGE_BLOCKS.get(page, []))


def normalize(page: str, blocks) -> list[str]:
    """Привести сохранённый порядок к валидному.

    Чужие/устаревшие имена отбрасываем, а блоки, которых не было в сохранённом
    порядке (страницу доработали), дописываем в конец — иначе новый блок
    исчезнет у всех, кто уже сохранил свою раскладку.
    """
    known = block_keys(page)
    order: list[str] = []
    for b in blocks or []:
        if b in known and b not in order:
            order.append(b)
    return order + [b for b in known if b not in order]


def as_orders(page: str, blocks) -> dict[str, int]:
    """{имя блока: order} — для style="order:N" в шаблоне."""
    return {name: i for i, name in enumerate(normalize(page, blocks))}


async def get_layout(db, user_id: uuid.UUID, page: str) -> dict[str, int]:
    """Сохранённый порядок блоков или порядок по умолчанию."""
    row = (
        await db.execute(
            select(UserPageLayout).where(
                UserPageLayout.user_id == user_id,
                UserPageLayout.page == page,
            )
        )
    ).scalar_one_or_none()
    return as_orders(page, row.blocks if row else None)


async def get_layout_order(db, user_id: uuid.UUID, page: str) -> list[str]:
    """Сохранённый порядок списком (для колонок таблицы)."""
    row = (
        await db.execute(
            select(UserPageLayout).where(
                UserPageLayout.user_id == user_id,
                UserPageLayout.page == page,
            )
        )
    ).scalar_one_or_none()
    return normalize(page, row.blocks if row else None)


async def save_layout(db, user_id: uuid.UUID, page: str, blocks) -> dict[str, int]:
    """Записать порядок блоков (одна строка на пользователя и страницу)."""
    order = normalize(page, blocks)
    row = (
        await db.execute(
            select(UserPageLayout).where(
                UserPageLayout.user_id == user_id,
                UserPageLayout.page == page,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(UserPageLayout(user_id=user_id, page=page, blocks=order))
    else:
        row.blocks = order
    await db.commit()
    return as_orders(page, order)
