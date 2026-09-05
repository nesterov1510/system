"""Единая матрица прав «роль × операция».

Раньше проверки прав были размазаны по роутерам и несогласованы: каталог
запчастей защищался ролью, а списание со склада, приём платежа и назначение
выплаты мастеру — нет. В результате пользователь только с ролью `master`
мог провести наличный платёж и выписать себе выплату по своему же ремонту.

Здесь — единственное место, где описано, кто что может. Роутеры обязаны
использовать эти функции, а не писать проверки ролей по месту.
"""
from app.db.models import UserRole

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
    return has_any_role(user, *CASHIER_ROLES)


def can_refund_payment(user) -> bool:
    """Отменить (сторнировать) платёж."""
    return has_any_role(user, ADMIN, MANAGER)


def can_edit_finances(user) -> bool:
    """Менять price_final / cost_amount / master_payout / paid."""
    return has_any_role(user, *FINANCE_ROLES)


def can_view_analytics(user) -> bool:
    return has_any_role(user, *ANALYTICS_ROLES)


# --------------------------------------------------------------------------
# Склад
# --------------------------------------------------------------------------
def can_edit_stock_catalog(user) -> bool:
    """Создавать/менять/архивировать позиции каталога запчастей."""
    return has_any_role(user, *STOCK_CATALOG_ROLES)


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
    return has_any_role(user, *SENIOR_ROLES)


def can_assign_masters(user) -> bool:
    """Назначать/менять мастеров и помощников на ремонт."""
    return has_any_role(user, *ASSIGN_ROLES)


def can_finish_repair(user) -> bool:
    """Перевести в «Готово к выдаче» и отправить клиенту SMS."""
    return has_any_role(user, *FINISH_ROLES)


def accepted_by_me(user, repair) -> bool:
    """Приёмку этого ремонта оформил именно данный пользователь."""
    accepted_by = getattr(repair, "accepted_by", None)
    return accepted_by is not None and accepted_by == user.id


def can_print(user, repair) -> bool:
    """Напечатать бланк/этикетку: мастер — свой ремонт или свою приёмку."""
    if has_any_role(user, *PRINT_QUEUE_ROLES) or not has_any_role(user, MASTER):
        return True
    # Мастер принял технику сам — этикетка на его приёмку печатается сразу,
    # даже когда исполнитель ещё не назначен (ремонт «в очереди», а назначает
    # его администратор/оператор). Иначе автопечать при приёмке упиралась в 403.
    if accepted_by_me(user, repair):
        return True
    return repair.master_id == user.id or any(
        link.user_id == user.id for link in repair.masters
    )


def can_access_repair(user, repair) -> bool:
    """Мастера видят свои ремонты и собственные приёмки; остальные роли — все."""
    if not is_master_only(user):
        return True
    if repair.master_id == user.id:
        return True
    # Своя приёмка: мастер оформил ремонт и обязан видеть его карточку,
    # даже если исполнителем назначат другого мастера.
    if accepted_by_me(user, repair):
        return True
    # Ремонт могут вести несколько мастеров — доступ есть у каждого из них.
    return any(m.user_id == user.id for m in repair.masters)


def can_delete_repair(user) -> bool:
    return has_any_role(user, ADMIN)


def can_delete_client(user) -> bool:
    return has_any_role(user, ADMIN)


def can_view_callcenter_queue(user) -> bool:
    return has_any_role(user, *CALLCENTER_ROLES)
