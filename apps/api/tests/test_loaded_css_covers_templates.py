"""Вкладки разделов обязаны быть описаны в подключённом CSS.

Причина дефекта: вкладки настроек и колл-центра используют `.tabs`, а правило
жило только в `static/app.css`. `base.html` подключает `msb/base.css`,
`msb/forms.css` и `msb/pwa.css` — `app.css` не грузится нигде, кроме публичной
страницы 404. В результате навигация по разделам рендерилась голыми ссылками:
без отступов, без подсветки активного раздела и без высоты под палец.

Список файлов тест берёт из самого `base.html`, поэтому проверка не разъедется
с разметкой, если набор стилей изменится.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "webui" / "static"
BASE = (
    Path(__file__).resolve().parent.parent / "app" / "webui" / "templates" / "base.html"
)


def _loaded_css() -> str:
    """Содержимое тех CSS, которые base.html реально подключает."""
    hrefs = re.findall(
        r'<link rel="stylesheet" href="/static/([^"]+\.css)"',
        BASE.read_text(encoding="utf-8"),
    )
    assert hrefs, "в base.html нет ни одного stylesheet — проверка бессмысленна"
    return "\n".join((STATIC / h).read_text(encoding="utf-8") for h in hrefs)


def test_tabs_are_styled_in_loaded_css():
    css = _loaded_css()
    assert re.search(r"\.tabs\{[^}]*display:flex", css), ".tabs не описан в подключённом CSS"
    assert ".tabs a.active" in css, "нет подсветки активной вкладки"
    # Высота под палец: на телефоне по вкладкам должно быть удобно попадать.
    block = re.search(r"\.tabs a,\.tabs button\{([^}]*)\}", css)
    assert block and "min-height:44px" in block.group(1), "вкладки ниже 44px"
