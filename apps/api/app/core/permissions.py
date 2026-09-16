"""Единая матрица прав «роль × операция».

Раньше проверки прав были размазаны по роутерам и несогласованы: каталог
запчастей защищался ролью, а списание со склада, приём платежа и назначение
выплаты мастеру — нет. В результате пользователь только с ролью `master`
мог провести наличный платёж и выписать себе выплату по своему же ремонту.

Здесь — единственное место, где описано, кто что может. Роутеры обязаны
использовать эти функции, а не писать проверки ролей по месту.
"""
from sqlalchemy import inspect

from app.db.models import RepairStatus, UserRole

ADMIN = UserRole.ADMIN.value
MANAGER = UserRole.MANAGER.value
OPERATOR = UserRole.OPERATOR.value
MASTER = UserRole.MASTER.value
CALLCENTER = UserRole.CALLCENTER.value

# «Старшие» роли: видят всё и распоряжаются деньгами.
SENIOR_ROLES = (ADMIN, MANAGER, OPERATOR)

# Роли, которые ведут кассу (приём/отмена платежей).
CASHIER_ROLES = (ADMIN, MANAGER, OPERATOR)

# Роли, которые вправе менять финансовые поля ремонта.
FINANCE_ROLES = (ADMIN, MANAGER, OPERATOR)

# Роли, которые управляют складским каталогом (позиции, цены, остатки).
STOCK_CATALOG_ROLES = (ADMIN, MANAGER)

# Роли, которые назначают мастеров на ремонт.
ASSIGN_ROLES = (ADMIN, OPERATOR)

# Роли, которые закрывают ремонт («Ремонт закончен») и пишут клиенту SMS.
FINISH_ROLES = (ADMIN, OPERATOR)

# Роли с доступом к аналитике.
ANALYTICS_ROLES = (ADMIN, MANAGER)

# Роли с доступом к очереди call-центра.
CALLCENTER_ROLES = (CALLCENTER, ADMIN, MANAGER, OPERATOR)

# Роли, которым доступна очередь печати.
PRINT_QUEUE_ROLES = (ADMIN, MANAGER, OPERATOR)


# ---------------------------------------------------------------------------
# Каталог функций, которые администратор может выдавать пользователю
# индивидуально — в дополнение к тому, что даёт роль (страница /admin/users,
# блок «Права доступа»). Ключ `key` хранится в User.extra_permissions;
# `roles` — роли, у которых функция включена по умолчанию (без гранта).
# ---------------------------------------------------------------------------
FEATURES: list[dict] = [
    {
        "key": "cash",
        "label": "Касса",
        "desc": "Принимать платежи от клиентов.",
        "roles": CASHIER_ROLES,
    },
    {
        "key": "refund",
        "label": "Сторно платежей",
        "desc": "Отменять (сторнировать) проведённые платежи.",
        "roles": (ADMIN, MANAGER),
    },
    {
        "key": "finance",
        "label": "Финансы ремонта",
        "desc": "Менять цену, себестоимость и выплату мастерам в ремонте.",
        "roles": FINANCE_ROLES,
    },
    {
        "key": "stock",
        "label": "Каталог запчастей",
        "desc": "Создавать, менять и архивировать позиции склада.",
        "roles": STOCK_CATALOG_ROLES,
    },
    {
        "key": "assign",
        "label": "Назначение мастеров",
        "desc": "Назначать и менять мастеров на ремонты.",
        "roles": ASSIGN_ROLES,
    },
    {
        "key": "finish",
        "label": "Закрытие ремонтов",
        "desc": "Переводить ремонт в «Завершён» и отправлять клиенту SMS.",
        "roles": FINISH_ROLES,
    },
    {
        "key": "analytics",
        "label": "Аналитика",
        "desc": "Просматривать аналитику и отчёты.",
        "roles": ANALYTICS_ROLES,
    },
    {
        "key": "callcenter",
        "label": "Call-центр",
        "desc": "Работать с очередью call-центра.",
        "roles": CALLCENTER_ROLES,
    },
    {
        "key": "device",
        "label": "Паспорт техники",
        "desc": "Менять марку/модель/серийник уже принятого ремонта.",
        "roles": SENIOR_ROLES,
    },
    {
        "key": "logs",
        "label": "Мониторинг логов",
        "desc": "Просматривать журнал отладки (Мониторинг в админке).",
        "roles": (ADMIN,),
    },
]

FEATURE_KEYS: set[str] = {f["key"] for f in FEATURES}
FEATURE_BY_KEY: dict[str, dict] = {f["key"]: f for f in FEATURES}


def role_grants_feature(user, key: str) -> bool:
    """Даёт ли РОЛЬ пользователя эту функцию (без учёта индивидуального гранта)."""
    feat = FEATURE_BY_KEY.get(key)
    if not feat or not user:
        return False
    return has_any_role(user, *feat["roles"])


def user_grants(user) -> set[str]:
    """Индивидуально выданные пользователю права (ключи функций)."""
    perms = getattr(user, "permissions", None)
    if isinstance(perms, list):
        return {p for p in perms if p in FEATURE_KEYS}
    return set()


def has_feature(user, key: str) -> bool:
    """Есть ли у пользователя право на функцию: роль ИЛИ индивидуальный грант.

    Администратор имеет все права всегда.
    """
    if not user:
        return False
    if user.has_role(ADMIN):
        return True
    return key in user_grants(user)


def has_any_role(user, *roles: str) -> bool:
    """Есть ли у пользователя хотя бы одна из ролей (учитывая дополнительные)."""
    return bool(user) and user.has_role(*roles)


def is_master_only(user) -> bool:
    """Роль мастера есть, а «старших» ролей с полным доступом — нет."""
    return has_any_role(user, MASTER) and not has_any_role(user, *SENIOR_ROLES)


# --------------------------------------------------------------------------
# Касса и деньги
# --------------------------------------------------------------------------
def can_take_payment(user) -> bool:
    """Принять платёж от клиента (касса)."""
    return has_any_role(user, *CASHIER_ROLES) or has_feature(user, "cash")


def can_refund_payment(user) -> bool:
    """Отменить (сторнировать) платёж."""
    return has_any_role(user, ADMIN, MANAGER) or has_feature(user, "refund")


def can_edit_finances(user) -> bool:
    """Менять price_final / cost_amount / master_payout / paid."""
    return has_any_role(user, *FINANCE_ROLES) or has_feature(user, "finance")


def can_view_analytics(user) -> bool:
    return has_any_role(user, *ANALYTICS_ROLES) or has_feature(user, "analytics")


# --------------------------------------------------------------------------
# Склад
# --------------------------------------------------------------------------
def can_edit_stock_catalog(user) -> bool:
    """Создавать/менять/архивировать позиции каталога запчастей."""
    return has_any_role(user, *STOCK_CATALOG_ROLES) or has_feature(user, "stock")


def can_add_repair_part(user) -> bool:
    """Списать запчасть под конкретный ремонт.

    Мастер может списывать деталь на ремонт, который ведёт сам, — но только
    без указания своей цены (цену подставляет складская). Право на произвольную
    цену есть у старших ролей.
    """
    return has_any_role(user, *SENIOR_ROLES, MASTER, CALLCENTER)


def can_set_repair_part_price(user) -> bool:
    """Задать/переопределить цену запчасти в ремонте."""
    return has_any_role(user, *SENIOR_ROLES)


def can_remove_repair_part(user) -> bool:
    """Убрать запчасть из ремонта (возврат на остаток)."""
    return has_any_role(user, *SENIOR_ROLES)


# --------------------------------------------------------------------------
# Ремонты
# --------------------------------------------------------------------------
def can_edit_device_info(user) -> bool:
    """Править марку/модель/серийный номер уже принятого ремонта.

    Паспорт техники — это то, что напечатано в бланке и на этикетке, поэтому
    меняют его старшие роли. Мастеру достаточно сообщить оператору.
    """
    return has_any_role(user, *SENIOR_ROLES) or has_feature(user, "device")


def can_assign_masters(user) -> bool:
    """Назначать/менять мастеров и помощников на ЛЮБОЙ ремонт (админ/оператор)."""
    return has_any_role(user, *ASSIGN_ROLES) or has_feature(user, "assign")


def can_assign_repair_masters(user, repair) -> bool:
    """Может ли пользователь менять состав мастеров ЭТОГО ремонта.

    Администратор и оператор — всегда. Мастер — в трёх случаях:

    * ремонт свободен (`is_free_repair`): тогда он берёт его себе (и может
      сразу добавить себе помощника);
    * ремонт уже его (`is_own_repair`): назначен напрямую или через список
      мастеров — тогда он добирает напарников и помощников, либо он сам
      оформил приёмку и исполнитель ещё не назначен.

    Чужой занятый ремонт мастер себе не забирает — в том числе чужую приёмку
    без исполнителя (она занята принявшим её мастером) и тот заказ, который он
    сам принял, но передал другому мастеру.
    """
    if can_assign_masters(user):
        return True
    if not has_any_role(user, MASTER):
        return False
    return is_own_repair(user, repair) or is_free_repair(repair)


def can_finish_repair(user) -> bool:
    """Перевести в «Завершён» и отправить клиенту SMS."""
    return has_any_role(user, *FINISH_ROLES) or has_feature(user, "finish")


def accepted_by_me(user, repair) -> bool:
    """Приёмку этого ремонта оформил именно данный пользователь."""
    accepted_by = getattr(repair, "accepted_by", None)
    return accepted_by is not None and accepted_by == user.id


def can_print(user, repair) -> bool:
    """Напечатать бланк/этикетку: мастер — свой ремонт либо своя приёмка в очереди."""
    if has_any_role(user, *PRINT_QUEUE_ROLES) or not has_any_role(user, MASTER):
        return True
    if repair.master_id == user.id:
        return True
    # Список исполнителей должен быть подгружен вместе с ремонтом. Если связь
    # не загружена, ленивое чтение в async-коде падает в MissingGreenlet —
    # считаем ремонт чужим, чтобы проверка прав отвечала 403, а не 500.
    if "masters" in inspect(repair).unloaded:
        return False
    if any(link.user_id == user.id for link in repair.masters):
        return True
    # Мастер принял технику сам, а исполнителя назначает администратор/оператор:
    # на этом этапе этикетку напечатать необходимо (её клеят на технику при
    # клиенте), поэтому приёмщику разрешена печать, ПОКА исполнитель не назначен.
    # Как только ремонт передали другому мастеру, печать — по общим правилам:
    # мастер работает только со своими заказами.
    return (
        accepted_by_me(user, repair)
        and repair.master_id is None
        and not repair.masters
    )


def can_access_repair(user, repair) -> bool:
    """Может ли пользователь ИЗМЕНЯТЬ этот ремонт.

    Мастер — только свои заказы (назначен напрямую или через список
    мастеров); старшие роли — любые. Проверка используется мутациями:
    смена статуса, финансы, запчасти, комментарии.
    """
    if not is_master_only(user):
        return True
    if repair.master_id == user.id:
        return True
    # Ремонт могут вести несколько мастеров — доступ есть у каждого из них.
    return any(m.user_id == user.id for m in repair.masters)


def can_view_repair(user, repair) -> bool:
    """Может ли пользователь ОТКРЫТЬ ремонт (только чтение).

    Мастер видит свои ремонты и свободные (которые можно взять себе) — те же
    границы, что и у списка «Все ремонты» (см.
    `services/repair_scope.master_visible`). Чужой ремонт с назначенным
    исполнителем ему недоступен, в том числе тот, что он сам принял при
    приёмке, но передал другому мастеру.

    Старшие роли и колл-центр видят всё. Менять чужой ремонт по-прежнему
    нельзя: мутации проверяются `can_access_repair`, а деньги/статусы/
    назначения — своими функциями прав.
    """
    if not is_master_only(user):
        return True
    return is_own_repair(user, repair) or is_free_repair(repair)


def _has_no_executor(repair) -> bool:
    """У ремонта нет исполнителя: ни прямого назначения, ни списка мастеров."""
    return repair.master_id is None and not list(getattr(repair, "masters", None) or [])


def is_own_repair(user, repair) -> bool:
    """Свой ли это ремонт для данного мастера.

    Зеркалит `services/repair_scope.own()`: исполнитель (напрямую или через
    список мастеров, в том числе помощник) **либо** собственная приёмка — но
    только пока исполнитель не назначен. С назначением исполнителя заказ
    становится заказом исполнителя, и у приёмщика он уже не «свой» (та же
    граница, что у права печати своей приёмки — `can_print`).
    """
    if repair.master_id == user.id:
        return True
    if any(m.user_id == user.id for m in (repair.masters or [])):
        return True
    return repair.accepted_by == user.id and _has_no_executor(repair)


def _accepted_by_master(repair) -> bool:
    """Ремонт принят пользователем с основной ролью «мастер».

    Роль приёмщика лежит в связанном пользователе, поэтому связь
    `accepted_by_user` должна быть подгружена вместе с ремонтом
    (`selectinload` в `_get_repair_or_404` и `_load_repair`). Если она не
    загружена, определить принадлежность нельзя — считаем приёмку чужой, чтобы
    не показать мастеру чужой заказ по ошибке.
    """
    if "accepted_by_user" in inspect(repair).unloaded:
        return True
    acceptor = repair.accepted_by_user
    if acceptor is None:
        return False
    return acceptor.role == MASTER


def is_free_repair(repair) -> bool:
    """Свободен ли ремонт — может ли любой мастер взять его себе.

    Зеркалит `services/repair_scope.free_to_take()` по уже загруженному объекту:
    исполнителя нет, принял не мастер (приёмка оператора/админа или публичной
    приёмки, ушедшая в общую очередь), ремонт не завершён и не выдан.

    Чужая приёмка без исполнителя свободной НЕ считается: её принял другой
    мастер, она уже занята им (он же печатает на неё этикетку).
    """
    if not _has_no_executor(repair):
        return False
    if _accepted_by_master(repair):
        return False
    if repair.status == RepairStatus.DONE or repair.issued_at is not None:
        return False
    return True


def can_delete_repair(user) -> bool:
    return has_any_role(user, ADMIN)


def can_delete_client(user) -> bool:
    return has_any_role(user, ADMIN)


def can_view_callcenter_queue(user) -> bool:
    return has_any_role(user, *CALLCENTER_ROLES) or has_feature(user, "callcenter")


def can_view_logs(user) -> bool:
    """Просмотр мониторинга логов — отдельная функция, не только роль admin.

    Администратор видит мониторинг всегда (см. `has_feature`); остальным
    право выдаётся индивидуально на странице «Сотрудники».
    """
    return has_feature(user, "logs")
