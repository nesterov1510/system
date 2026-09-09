"""Jinja2 environment and shared template helpers/filters.

Все шаблоны лежат в app/webui/templates. Денежный формат берёт символ валюты
из настроек (туркменский манат «ман.»), а не хардкодит ₽.
"""
import json
from datetime import datetime
from pathlib import Path

from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

TEMPLATES_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
    enable_async=True,
)


def _money(value, symbol: str = "ман.") -> str:
    """12345.6 -> '12 346 ман.' (0 знаков дробной части для TMT)."""
    if value is None or value == "":
        return "—"
    try:
        num = round(float(value))
    except (TypeError, ValueError):
        return str(value)
    s = f"{num:,}".replace(",", " ")  # неразрывный пробел как разделитель тысяч
    return f"{s} {symbol}"


def _dt(value, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(fmt)


def _date(value) -> str:
    return _dt(value, "%d.%m.%Y")


def _yesno(value) -> str:
    return "Да" if value else "Нет"


def _class_icon(raw) -> str:
    from app.webui.catalog import class_icon
    return class_icon(raw)


def _device_class(raw) -> str:
    from app.webui.catalog import normalize_class
    return normalize_class(raw)


def _stage_label(status) -> str:
    from app.webui.catalog import STAGES
    for key, label, statuses in STAGES:
        if status in statuses:
            return label
    return "В работе"


def _status_chip_class(status) -> str:
    colors = {
        "Принято": "gray", "Диагностика": "amber", "Согласование": "violet",
        "Ожидание запчастей": "violet", "В ремонте": "amber",
        "Готово к выдаче": "green", "Выдано": "green", "Не забрано": "red",
        "Архив": "gray", "Отказ": "red",
    }
    return colors.get(status, "gray")


def _active(ep: str | None, href: str) -> str:
    """is-active для навигации: /repairs подсвечивается и на карточке."""
    ep = ep or ""
    if ep == href:
        return "is-active"
    if href == "/repairs" and ep.startswith("/repairs"):
        return "is-active"
    return ""


def _tojson(value) -> Markup:
    return Markup(json.dumps(value, ensure_ascii=False, default=str))

env.filters["tojson"] = _tojson
env.filters["money"] = _money
env.filters["dt"] = _dt
env.filters["date"] = _date
env.filters["yesno"] = _yesno
env.filters["nav_active"] = _active
env.filters["class_icon"] = _class_icon
env.filters["device_class"] = _device_class
env.filters["stage_label"] = _stage_label
env.filters["status_chip"] = _status_chip_class
env.globals["currency_sym"] = "ман."


def render(template_name: str, **context) -> str:
    """Синхронный рендер (используется в async-обёртке через render_async)."""
    return env.get_template(template_name).render(**context)


async def render_async(template_name: str, **context) -> str:
    """Единая точка рендера страницы. Окружение включено в async-режиме.

    Важно: НЕ используем starlette.Jinja2Templates — он создаёт собственное
    окружение без async, из-за чего `render_async` падал с RuntimeError.
    """
    template = env.get_template(template_name)
    return await template.render_async(**context)


async def html(template_name: str, status_code: int = 200, **context) -> HTMLResponse:
    """Удобная обёртка: рендер шаблона в HTMLResponse."""
    content = await render_async(template_name, **context)
    return HTMLResponse(content, status_code=status_code)
