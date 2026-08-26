"""PDF blank rendering (Epson EcoTank L3250 = A4 inkjet, no ESC/POS).

Uses ReportLab + DejaVuSans for Cyrillic. The blank layout is **data-driven**:
an editable template (stored in the `print_templates` table, JSON) selects which
fields to show, the brand/title/footer, paper size, and the legal text. Nothing
business-specific is hardcoded in the layout code.
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
        "fault",
        "accepted_by",
        "master",
        "storage_until",
        "eta",
    ],
    "legal_text": None,
    "footer": "Спасибо, что выбрали нас!",
    "signature": True,
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
    accepted_by: str,
    master: str,
    eta_days: str,
    legal_text: str,
    storage_until: str,
    qr_url: str,
) -> bytes:
    t = normalize_template(template)
    _register_fonts()

    paper = t.get("paper", "A4").upper()
    page = A4 if paper == "A4" else A5
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=page)
    w, h = page
    left = 12 * mm
    top = h - 12 * mm

    brand = t.get("brand") or "RemontFlow"
    title = t.get("title") or ""
    subtitle = t.get("subtitle") or ""
    footer = t.get("footer") or ""

    def draw(text, x, y, size=10, bold=False):
        c.setFont(FONT_BOLD if bold else FONT, size)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(x, y, text)

    y = top

    draw(brand.upper(), left, y, size=16, bold=True)
    y -= 8 * mm
    if subtitle:
        try:
            sub = subtitle.format(city=city_name, branch=branch_name)
        except (KeyError, IndexError):
            sub = subtitle
        draw(sub, left, y, size=9)
        y -= 6 * mm
    if title:
        draw(title, left, y, size=10, bold=True)
        y -= 6 * mm

    # Big repair number
    draw("№ ремонта", left, y, size=9)
    y -= 7 * mm
    draw(number, left, y, size=26, bold=True)
    y -= 12 * mm

    draw(f"Дата приёма: {accepted_at}", left, y)
    y -= 6 * mm

    # Field values keyed by template field name.
    values = {
        "client": client_name,
        "phone": client_phone,
        "device": device,
        "serial": serial,
        "complect": complectation,
        "fault": fault,
        "accepted_by": accepted_by,
        "master": master,
        "storage_until": storage_until,
        "eta": f"{eta_days} дн" if eta_days else "—",
    }

    for field in t.get("fields", []):
        label = FIELD_LABELS.get(field, field)
        value = values.get(field) or "—"
        draw(f"{label}:", left, y, size=9)
        draw(value, left + 40 * mm, y, size=9, bold=True)
        y -= 5.5 * mm

    # Legal text (from template override or DB setting).
    legal = t.get("legal_text") or legal_text or ""
    if legal:
        y -= 4 * mm
        draw("УСЛОВИЯ ХРАНЕНИЯ", left, y, size=9, bold=True)
        y -= 5 * mm
        for chunk in simpleSplit(legal, FONT, 8, w - 2 * left):
            draw(chunk, left, y, size=8)
            y -= 4.5 * mm

    # QR in top-right area.
    try:
        qr_buf = _qr_png(qr_url)
        c.drawImage(qr_buf, w - 45 * mm, h - 52 * mm, width=33 * mm, height=33 * mm)
        draw("Статус ремонта по QR", w - 45 * mm, h - 56 * mm, size=7)
    except Exception:
        draw(f"QR: {qr_url}", w - 60 * mm, h - 30 * mm, size=6)

    # Footer.
    if footer:
        c.setFont(FONT, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawCentredString(w / 2, 14 * mm, footer)

    # Signature block.
    if t.get("signature", True):
        y = 20 * mm
        c.setFillColorRGB(0, 0, 0)
        c.line(left, y, left + 70 * mm, y)
        c.line(w - 70 * mm - left, y, w - left, y)
        draw("Подпись клиента", left, y - 5 * mm, size=8)
        draw("Подпись приёмщика", w - 70 * mm - left, y - 5 * mm, size=8)

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
