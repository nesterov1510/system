"""PDF blank rendering (Epson EcoTank L3250 = A4 inkjet, no ESC/POS).

Uses ReportLab + DejaVuSans for Cyrillic. Text parts (legal text, brand)
come from DB settings — never hardcoded. A Handlebars/JSON template editor
(admin) is a later iteration; this module renders the default A4 layout.
"""
import io
import os

from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
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
    number: str,
    accepted_at: str,
    city_name: str,
    branch_name: str,
    client_name: str,
    client_phone: str,
    device: str,
    complectation: str,
    fault: str,
    accepted_by: str,
    master: str,
    legal_text: str,
    storage_until: str,
    qr_url: str,
    brand: str,
    paper: str = "A4",
) -> bytes:
    _register_fonts()

    page = A4 if paper.upper() == "A4" else A5
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=page)
    w, h = page
    left = 12 * mm
    top = h - 12 * mm

    def line(text, x, y, size=10, bold=False, color=None):
        c.setFont(FONT_BOLD if bold else FONT, size)
        if color:
            c.setFillColor(color)
        else:
            c.setFillColorRGB(0, 0, 0)
        c.drawString(x, y, text)

    y = top

    line(brand.upper(), left, y, size=16, bold=True)
    y -= 8 * mm
    line(f"Сервисный центр · {city_name} · {branch_name}", left, y, size=9)
    y -= 6 * mm

    # Big repair number
    line("№ ремонта", left, y, size=9)
    y -= 7 * mm
    line(number, left, y, size=26, bold=True)
    y -= 12 * mm

    line(f"Дата приёма: {accepted_at}", left, y)
    y -= 6 * mm

    def row(label, value):
        nonlocal y
        line(f"{label}:", left, y, size=9)
        line(value or "—", left + 40 * mm, y, size=9, bold=True)
        y -= 5.5 * mm

    row("Клиент", client_name)
    row("Телефон", client_phone)
    row("Техника", device)
    row("Комплект", complectation)
    row("Неисправность", fault)
    row("Принял", accepted_by)
    row("Мастер", master)
    row("Хранение до", storage_until)

    y -= 4 * mm
    line("УСЛОВИЯ ХРАНЕНИЯ", left, y, size=9, bold=True)
    y -= 5 * mm
    # Wrap legal text
    from reportlab.lib.utils import simpleSplit

    for chunk in simpleSplit(legal_text, FONT, 8, w - 2 * left):
        line(chunk, left, y, size=8)
        y -= 4.5 * mm

    # QR in top-right area
    try:
        qr_buf = _qr_png(qr_url)
        c.drawImage(qr_buf, w - 45 * mm, h - 52 * mm, width=33 * mm, height=33 * mm)
        line("Статус ремонта по QR", w - 45 * mm, h - 56 * mm, size=7)
    except Exception:
        line(f"QR: {qr_url}", w - 60 * mm, h - 30 * mm, size=6)

    # Signature block
    y = 18 * mm
    c.line(left, y, left + 70 * mm, y)
    c.line(w - 70 * mm - left, y, w - left, y)
    line("Подпись клиента", left, y - 5 * mm, size=8)
    line("Подпись приёмщика", w - 70 * mm - left, y - 5 * mm, size=8)

    c.showPage()
    c.save()
    return buf.getvalue()
