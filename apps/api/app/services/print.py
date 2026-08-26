"""PDF blank rendering (Epson EcoTank L3250 = A4 inkjet, no ESC/POS).

Uses ReportLab + DejaVuSans for Cyrillic. The blank layout is **data-driven**:
an editable template (stored in the `print_templates` table, JSON) selects which
fields to show, the brand/title/footer, paper size, legal text, and layout.

Layout modes (template field `layout`):
  - "one-per-page" : каждый экземпляр на отдельной странице (по умолчанию).
  - "two-per-page" : 2 экземпляра (клиент + сервис) на ОДНОМ листе A4,
                     вертикально, с линией разреза между ними (потом порезать).
"""
import io
import json
import os

from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

# Cyrillic-capable font. On Debian/Ubuntu this ships with fonts-dejavu-core.
FONT_PATH = os.environ.get(
    "REMONTFLOW_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)
FONT_PATH_BOLD = os.environ.get(
    "REMONTFLOW_FONT_PATH_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
)

FONT = "DejaVu"
FONT_BOLD = "DejaVu-Bold"

# Field keys available in a template, mapped to human labels.
FIELD_LABELS = {
    "client": "Клиент",
    "phone": "Телефон",
    "device": "Техника",
    "serial": "Серийник",
    "complect": "Комплект",
    "fault": "Неисправность",
    "condition": "Внешний вид",
    "accepted_by": "Принял",
    "master": "Мастер",
    "storage_until": "Хранение до",
    "eta": "Срок (дней)",
}

AVAILABLE_FIELDS = list(FIELD_LABELS.keys())

# Default template. `legal_text: null` => use the DB setting `legal_text`.
DEFAULT_TEMPLATE = {
    "name": "Бланк приёма (A4, дефолт)",
    "paper": "A4",
    "brand": "RemontFlow",
    "title": "БЛАНК ПРИЁМА ТЕХНИКИ",
    "subtitle": "Сервисный центр · {city} · {branch}",
    "fields": [
        "client",
        "phone",
        "device",
        "serial",
        "complect",
        "condition",
        "fault",
        "accepted_by",
        "master",
        "storage_until",
        "eta",
    ],
    "legal_text": None,
    "footer": "Спасибо, что выбрали нас!",
    "signature": True,
    # Количество экземпляров договора (клиент + сервис).
    "copies": 2,
    # Раскладка: one-per-page | two-per-page (2 на одном листе).
    "layout": "two-per-page",
}


def normalize_template(body: dict) -> dict:
    """Fill missing keys from the default template."""
    t = dict(DEFAULT_TEMPLATE)
    if body:
        t.update(body)
    # guard fields list
    t["fields"] = [f for f in t.get("fields", []) if f in AVAILABLE_FIELDS]
    return t


def _register_fonts() -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, FONT_PATH))
    if FONT_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_PATH_BOLD))


def _qr_png(data: str) -> io.BytesIO:
    import qrcode

    img = qrcode.make(data, box_size=4, border=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def render_blank_pdf(
    *,
    template: dict,
    number: str,
    accepted_at: str,
    city_name: str,
    branch_name: str,
    client_name: str,
    client_phone: str,
    device: str,
    serial: str,
    complectation: str,
    fault: str,
    condition: str = "",
    accepted_by: str,
    master: str,
    eta_days: str,
    legal_text: str,
    storage_until: str,
    qr_url: str,
    currency_symbol: str = "ман.",
    consent_repair_text: str = "",
    consent_repair: bool = False,
) -> bytes:
    t = normalize_template(template)
    _register_fonts()

    layout = t.get("layout", "one-per-page")
    copies = max(1, int(t.get("copies", 2) or 2))
    copy_labels = ["ЭКЗЕМПЛЯР КЛИЕНТА", "ЭКЗЕМПЛЯР СЕРВИСА"]

    brand = t.get("brand") or "RemontFlow"
    title = t.get("title") or ""
    subtitle = t.get("subtitle") or ""
    footer = t.get("footer") or ""

    values = {
        "client": client_name,
        "phone": client_phone,
        "device": device,
        "serial": serial,
        "complect": complectation,
        "fault": fault,
        "condition": condition,
        "accepted_by": accepted_by,
        "master": master,
        "storage_until": storage_until,
        "eta": f"{eta_days} дн" if eta_days else "—",
    }
    legal = t.get("legal_text") or legal_text or ""

    def draw_copy(c, w, top, bottom, label: str, s: float) -> None:
        """Рисует один экземпляр в вертикальной полосе [bottom, top]. s — масштаб."""
        left = 12 * mm * s
        content_w = w - 2 * left

        def draw(text, x, y, size, bold=False, color=None, align=None):
            c.setFont(FONT_BOLD if bold else FONT, size)
            c.setFillColor(color if color else (0, 0, 0))
            if align == "right":
                c.drawRightString(x, y, text)
            elif align == "center":
                c.drawCentredString(x, y, text)
            else:
                c.drawString(x, y, text)

        y = top - 6 * mm * s

        # Метка экземпляра.
        if label:
            draw(label, w - left, y, 8 * s, bold=True, align="right")
            y -= 7 * mm * s

        draw(brand.upper(), left, y, 15 * s, bold=True)
        y -= 7 * mm * s

        if subtitle:
            try:
                sub = subtitle.format(city=city_name, branch=branch_name)
            except (KeyError, IndexError):
                sub = subtitle
            draw(sub, left, y, 8 * s)
            y -= 5.5 * mm * s
        if title:
            draw(title, left, y, 9 * s, bold=True)
            y -= 5.5 * mm * s

        draw("№ ремонта", left, y, 8 * s)
        y -= 6 * mm * s
        draw(number, left, y, 22 * s, bold=True)
        y -= 10 * mm * s

        draw(f"Дата приёма: {accepted_at}", left, y, 8 * s)
        y -= 5 * mm * s

        # Поля.
        value_x = left + 38 * mm * s
        for field in t.get("fields", []):
            label_ = FIELD_LABELS.get(field, field)
            value = values.get(field) or "—"
            draw(f"{label_}:", left, y, 8 * s)
            draw(value, value_x, y, 8 * s, bold=True)
            y -= 4.5 * mm * s

        # Условия хранения.
        if legal:
            y -= 3.5 * mm * s
            draw("УСЛОВИЯ ХРАНЕНИЯ", left, y, 8 * s, bold=True)
            y -= 4.5 * mm * s
            for chunk in simpleSplit(legal, FONT, 7 * s, content_w):
                draw(chunk, left, y, 7 * s)
                y -= 4 * mm * s

        # Согласие на диагностику и ремонт.
        if consent_repair_text:
            y -= 3.5 * mm * s
            draw("СОГЛАСИЕ НА ДИАГНОСТИКУ И РЕМОНТ", left, y, 8 * s, bold=True)
            y -= 4.5 * mm * s
            for chunk in simpleSplit(consent_repair_text, FONT, 7 * s, content_w):
                draw(chunk, left, y, 7 * s)
                y -= 4 * mm * s
            y -= 3 * mm * s
            marker = "[X] Согласен" if consent_repair else "[ ] Согласен"
            draw(marker, left, y, 8 * s, bold=True)

        # QR в правом верхнем углу копии.
        try:
            qr_buf = _qr_png(qr_url)
            qr_size = 26 * mm * s
            qr_x = w - left - qr_size
            qr_y = top - 6 * mm * s - qr_size
            c.drawImage(qr_buf, qr_x, qr_y, width=qr_size, height=qr_size)
            draw("QR статус", qr_x, qr_y - 3.5 * mm * s, 6 * s)
        except Exception:
            pass

        # Footer (внизу копии).
        if footer:
            draw(footer, w / 2, bottom + 6 * mm * s, 7 * s, color=(0.35, 0.35, 0.35), align="center")

        # Подписи (внизу копии).
        if t.get("signature", True):
            sig_y = bottom + 13 * mm * s
            c.setFillColorRGB(0, 0, 0)
            c.setLineWidth(0.5)
            c.line(left, sig_y, left + 62 * mm * s, sig_y)
            c.line(w - 62 * mm * s - left, sig_y, w - left, sig_y)
            draw("Подпись клиента", left, sig_y - 4 * mm * s, 7 * s)
            draw("Подпись сервиса", w - 62 * mm * s - left, sig_y - 4 * mm * s, 7 * s)

    buf = io.BytesIO()

    if layout == "two-per-page":
        # 2 экземпляра на одном листе A4 (вертикально) + линия разреза.
        page = A4
        c = canvas.Canvas(buf, pagesize=page)
        w, h = page
        margin = 7 * mm
        gutter = 10 * mm
        half = (h - 2 * margin - gutter) / 2

        regions = [
            (h - margin, h - margin - half),                                  # верх
            (h - margin - half - gutter, h - margin - half - gutter - half),  # низ
        ]

        for i in range(min(copies, 2)):
            top, bottom = regions[i]
            label = copy_labels[i] if i < len(copy_labels) else f"ЭКЗЕМПЛЯР {i + 1}"
            draw_copy(c, w, top, bottom, label, s=0.66)

        # Линия разреза между экземплярами.
        cut_y = (regions[0][1] + regions[1][0]) / 2
        c.setDash(3, 3)
        c.setStrokeColorRGB(0.4, 0.4, 0.4)
        c.setLineWidth(0.4)
        c.line(margin, cut_y, w - margin, cut_y)
        c.setDash()
        c.setFont(FONT, 6.5)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawCentredString(w / 2, cut_y - 3.2 * mm, "— ✂ разрез ✂ —")
        c.save()
    else:
        # Каждый экземпляр на отдельной странице.
        paper = t.get("paper", "A4").upper()
        page = A4 if paper == "A4" else A5
        c = canvas.Canvas(buf, pagesize=page)
        w, h = page
        margin = 12 * mm
        for i in range(copies):
            label = copy_labels[i] if i < len(copy_labels) else f"ЭКЗЕМПЛЯР {i + 1}"
            top = h - margin
            bottom = margin
            draw_copy(c, w, top, bottom, label, s=1.0)
            c.showPage()
        c.save()

    return buf.getvalue()


def template_to_body(template: dict) -> str:
    return json.dumps(normalize_template(template), ensure_ascii=False)


def body_to_template(body: str) -> dict:
    try:
        data = json.loads(body) if body else {}
    except (ValueError, TypeError):
        data = {}
    return normalize_template(data)
