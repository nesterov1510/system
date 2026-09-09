"""Справочники и навигация по ролям веб-интерфейса (Jinja2).

Здесь — единый для всего веб-интерфейса список классов техники (значения
совпадают с тем, что понимает нумератор `app.services.numbering`), иконки и
матрица видимости разделов навигации по ролям.
"""

# --- Классы техники (форма приёмки и всё остальное) ---
DEVICE_CLASSES = [
    {"value": "Телевизоры", "label": "Телевизоры", "icon": "📺"},
    {"value": "Компьютеры", "label": "Компьютеры", "icon": "🖥️"},
    {"value": "Бытовая техника", "label": "Бытовая техника", "icon": "🧺"},
    {"value": "Другое", "label": "Другое", "icon": "⚙️"},
]

# Старые значения device_type -> класс (маппинг для уже принятых ремонтов).
LEGACY_CLASS = {
    "ТВ": "Телевизоры",
    "Монитор": "Компьютеры",
    "Компьютер": "Компьютеры",
    "Ноутбук": "Компьютеры",
    "Аудио": "Бытовая техника",
    "Бытовая": "Бытовая техника",
    "Другое": "Другое",
}

# Популярные марки — чипсы быстрого выбора в форме (не обязательный список).
COMMON_BRANDS = ["Samsung", "LG", "Xiaomi", "Sony", "Toshiba", "Philips",
                 "Hisense", "Haier", "HP", "Lenovo", "Apple", "Asus"]


_CLASS_VALUES = {c["value"] for c in DEVICE_CLASSES}


def normalize_class(raw: str | None) -> str:
    """Привести любое (в т.ч. старое) значение device_type к текущему классу."""
    if not raw:
        return "Другое"
    if raw in _CLASS_VALUES:
        return raw
    return LEGACY_CLASS.get(raw, raw)


def class_icon(raw: str | None) -> str:
    for c in DEVICE_CLASSES:
        if c["value"] == normalize_class(raw):
            return c["icon"]
    return "⚙️"


# --- Навигация: какие разделы видит роль ---
# Пункты основного меню (href -> подпись/иконка).
NAV_ITEMS = [
    ("/dashboard", "Панель", "📊"),
    ("/repairs", "Все ремонты", "🧾"),
    ("/repairs/new", "Приёмка", "➕"),
    ("/clients", "Клиенты", "👤"),
    ("/callcenter", "Call-центр", "📞"),
    ("/chat", "Чат", "💬"),
    ("/notifications", "Уведомления", "🔔"),
    ("/parts", "Склад", "🔩"),
    ("/prices", "Прайс-лист", "💰"),
]

# Админ-разделы (видны только роли admin).
ADMIN_NAV = [
    ("/admin/users", "Сотрудники", "👥"),
    ("/admin/logs", "Мониторинг", "📈"),
    ("/admin/settings", "Настройки", "⚙️"),
]

# Видимость разделов по роли (порт ROLE_SCOPES из catalog.ts).
ROLE_SCOPES = {
    "admin": "all",
    "manager": ["/repairs", "/repairs/new", "/clients", "/callcenter",
                "/chat", "/parts", "/prices", "/dashboard", "/profile",
                "/notifications"],
    # Оператор — всё, кроме аналитики и админ-разделов.
    "operator": ["/repairs", "/repairs/new", "/clients", "/callcenter",
                 "/chat", "/parts", "/prices", "/profile", "/notifications"],
    # Мастер — приёмка, свои ремонты, чат и профиль.
    "master": ["/repairs", "/repairs/new", "/chat", "/profile", "/notifications"],
    "callcenter": ["/repairs", "/clients", "/callcenter", "/chat", "/profile",
                   "/notifications"],
}


def _roles_of(user) -> list[str]:
    """Все роли пользователя (основная + дополнительные), без дублей."""
    if user is None:
        return []
    try:
        return list(user.roles)
    except (AttributeError, TypeError):
        return [getattr(user, "role", "")]


# Индивидуальные гранты (страница «Сотрудники» → «Права доступа») открывают
# соответствующие разделы навигации даже тем, у кого роль их не видит.
FEATURE_NAV = {
    "analytics": "/dashboard",
    "stock": "/parts",
    "callcenter": "/callcenter",
    "logs": "/admin/logs",
}


def can_view(user, href: str) -> bool:
    """Доступен ли раздел `href` пользователю (объединение прав всех ролей)."""
    roles = _roles_of(user)
    # Любая админ-роль среди ролей даёт всё.
    if "admin" in roles:
        return True
    for r in roles:
        scope = ROLE_SCOPES.get(r)
        if scope == "all":
            return True
        if isinstance(scope, list) and href in scope:
            return True
    # Индивидуальные гранты функций (сверх роли).
    from app.core.permissions import user_grants

    for key, target in FEATURE_NAV.items():
        if href == target and key in user_grants(user):
            return True
    return False


def visible_nav(user) -> list[tuple[str, str, str]]:
    """Пункты основного меню, доступные пользователю."""
    return [item for item in NAV_ITEMS if can_view(user, item[0])]


def visible_admin_nav(user) -> list[tuple[str, str, str]]:
    """Пункты «Управление»: у admin — все, у остальных — только выданные."""
    if "admin" in _roles_of(user):
        return ADMIN_NAV
    # Не-админ с индивидуальным грантом на мониторинг логов видит только его.
    from app.core.permissions import can_view_logs

    items = []
    if can_view_logs(user):
        items.append(("/admin/logs", "Мониторинг", "📈"))
    return items


# Этапы доски «Все ремонты» (порт STAGE_STATUSES из routers/repairs.py).
STAGES = [
    ("new", "Новые", ["Принято"]),
    ("diag", "Диагностика", ["Диагностика"]),
    ("work", "В работе", ["Согласование", "Ожидание запчастей", "В ремонте"]),
    ("done", "Завершены", ["Готово к выдаче", "Выдано", "Не забрано", "Архив", "Отказ"]),
]
