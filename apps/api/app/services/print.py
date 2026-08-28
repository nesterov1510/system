"""PDF blank rendering (Epson EcoTank L3250 = A4 inkjet, no ESC/POS).

Uses ReportLab + DejaVuSans for Cyrillic. The blank layout is **data-driven**:
an editable template (stored in the `print_templates` table, JSON) selects which
fields to show, the brand/title/footer, paper size, legal text, and layout.

Layout modes (template field `layout`):
  - "one-per-page" : каждый экземпляр на отдельной странице (по умолчанию).
  - "two-per-page" : 2 экземпляра (клиент + сервис) на ОДНОМ листе A4,
                     вертикально, с линией разреза между ними (потом порезать).
  - "turkmen"      : туркменская форма приёмки (1 экземпляр, A4).
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
    "MSB_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)
FONT_PATH_BOLD = os.environ.get(
    "MSB_FONT_PATH_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
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
    "name": "Бланк приёма (Turkmen)",
    "paper": "A4",
    "brand": "MSB — Мастер Сервис Бюро",
    "title": "Bejergi üçin kabul edilen enjamlaryň hasaba alyş kagyzy",
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
    "footer": "MSB — Мастер Сервис Бюро",
    "signature": True,
    "copies": 1,
    "layout": "turkmen",
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


# ---------------------------------------------------------------------------
# Turkmen acceptance form — "Bejergi üçin kabul edilen enjamlaryň hasaba alyş kagyzy"
# ---------------------------------------------------------------------------


def _render_turkmen_form(
    *,
    t: dict,
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
    condition: str,
    accepted_by: str,
    master: str,
    eta_days: str,
    legal_text: str,
    storage_until: str,
    qr_url: str,
    currency_symbol: str,
    consent_repair_text: str,
    consent_repair: bool,
) -> bytes:
    """Render the Turkmen acceptance form PDF (1 copy, A4)."""
    _register_fonts()
    page = A4
    w, h = page
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=page)

    # Margins
    left_margin = 15 * mm
    right_margin = w - 15 * mm
    content_w = right_margin - left_margin

    # Helper: draw text
    def draw(text, x, y, size=8, bold=False, color=None, align=None):
        c.setFont(FONT_BOLD if bold else FONT, size)
        if color:
            c.setFillColorRGB(*color)
        else:
            c.setFillColorRGB(0, 0, 0)
        if align == "right":
            c.drawRightString(x, y, text)
        elif align == "center":
            c.drawCentredString(x, y, text)
        else:
            c.drawString(x, y, text)

    # Helper: draw underline
    def draw_line(x, y, length):
        c.setStrokeColorRGB(0.3, 0.3, 0.3)
        c.setLineWidth(0.4)
        c.line(x, y, x + length, y)

    # Helper: draw a field with label and underlined blank
    def draw_field(label, value, x, y, label_size=7, value_size=7, blank_width=60*mm):
        draw(label, x, y, label_size, bold=True)
        label_w = c.stringWidth(label, FONT_BOLD, label_size)
        val_x = x + label_w + 1.5 * mm
        val_end = val_x + blank_width
        draw(str(value) if value else "", val_x, y, value_size)
        draw_line(val_x, y - 0.5 * mm, blank_width)

    # Helper: draw a row with two columns
    def draw_row_two_col(left_label, left_value, right_label, right_value,
                         y, left_label_x=None, right_label_x=None):
        if left_label_x is None:
            left_label_x = left_margin
        if right_label_x is None:
            right_label_x = left_margin + content_w / 2 + 5 * mm
        draw_field(left_label, left_value, left_label_x, y)
        draw_field(right_label, right_value, right_label_x, y)

    # --- Header area ---
    y = h - 15 * mm

    # Brand / MSB logo area
    draw("MSB", left_margin, y, 14, bold=True)
    draw("Мастер Сервис Бюро", left_margin + 22 * mm, y + 1 * mm, 7, bold=True)
    y -= 6 * mm

    # Title
    title = t.get("title") or "Bejergi üçin kabul edilen enjamlaryň hasaba alyş kagyzy"
    draw(title, left_margin, y, 9, bold=True)
    y -= 6 * mm

    # Subtitle with city/branch
    subtitle = t.get("subtitle") or ""
    if subtitle:
        try:
            sub_text = subtitle.format(city=city_name, branch=branch_name)
        except (KeyError, IndexError):
            sub_text = subtitle
        draw(sub_text, left_margin, y, 7)
        y -= 5 * mm

    # Divider line
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.setLineWidth(0.8)
    c.line(left_margin, y, right_margin, y)
    y -= 6 * mm

    # QR code in top-right
    try:
        qr_buf = _qr_png(qr_url)
        qr_size = 20 * mm
        qr_x = right_margin - qr_size - 2 * mm
        qr_y = y - qr_size
        c.drawImage(qr_buf, qr_x, qr_y, width=qr_size, height=qr_size)
        draw("QR", qr_x + qr_size / 2, qr_y - 3 * mm, 5, align="center")
    except Exception:
        pass

    # Number
    draw(f"№ {number}", left_margin, y, 10, bold=True)
    y -= 5 * mm

    # --- Row 1: Gelen wagty / REG / Paýdar (AKS) / Kassa ---
    row_y = y
    draw("Gelen wagty:", left_margin, row_y, 7, bold=True)
    draw(accepted_at, left_margin + 25 * mm, row_y, 7)
    draw_line(left_margin + 25 * mm, row_y - 0.5 * mm, 35 * mm)

    draw("REG:", left_margin + 65 * mm, row_y, 7, bold=True)
    draw(number, left_margin + 72 * mm, row_y, 7)
    draw_line(left_margin + 72 * mm, row_y - 0.5 * mm, 20 * mm)

    draw("Paýdar (AKS):", left_margin + 100 * mm, row_y, 7, bold=True)
    draw_line(left_margin + 100 * mm, row_y - 0.5 * mm, 15 * mm)

    draw("Kassa", left_margin + 120 * mm, row_y, 7, bold=True)
    draw_line(left_margin + 120 * mm, row_y - 0.5 * mm, 18 * mm)
    y -= 6 * mm

    # --- Row 2: Telefon belgisi / 1. Inžiner ---
    draw_row_two_col(
        "Telefon belgisi:", client_phone,
        "1. Inžiner:", "",
        y
    )
    y -= 5.5 * mm

    # --- Row 3: Eýesiniň ady / 2. Inžiner ---
    draw_row_two_col(
        "Eýesiniň ady:", client_name,
        "2. Inžiner:", "",
        y
    )
    y -= 5.5 * mm

    # --- Row 4: M_Model / 3. Inžiner ---
    draw_row_two_col(
        "M_Model:", device,
        "3. Inžiner:", "",
        y
    )
    y -= 5.5 * mm

    # --- Row 5: Gürleşilen baha / 4. Inžiner ---
    draw_row_two_col(
        "Gürleşilen baha:", "",
        "4. Inžiner:", "",
        y
    )
    y -= 5.5 * mm

    # --- Row 6: Aýdylan wagty / Ammar (Склад) ---
    draw_row_two_col(
        "Aýdylan wagty:", "",
        "Ammar (Склад):", "",
        y
    )
    y -= 7 * mm

    # --- Görkezme (description) ---
    draw("Görkezme:", left_margin, y, 7, bold=True)
    y -= 5 * mm
    for i in range(3):
        draw_line(left_margin, y, content_w)
        y -= 5 * mm

    y -= 2 * mm

    # --- Kemçilik (defects) — 3 rows ---
    for i in range(1, 4):
        draw(f"{i}. Kemçilik:", left_margin, y, 7, bold=True)
        draw_line(left_margin + 23 * mm, y - 0.5 * mm, 45 * mm)
        draw("Kim taraplaýyn barlanyldy:", left_margin + 73 * mm, y, 7, bold=True)
        draw_line(left_margin + 73 * mm + 48 * mm, y - 0.5 * mm, 10 * mm)
        draw("/Goly", left_margin + 73 * mm + 48 * mm + 11 * mm, y, 7, bold=True)
        draw_line(left_margin + 73 * mm + 48 * mm + 11 * mm + 10 * mm, y - 0.5 * mm, 15 * mm)
        y -= 5.5 * mm

    y -= 3 * mm

    # --- Dakylan ätiýaçlyk şaýlary (attached spare parts) ---
    draw("Dakylan ätiýaçlyk şaýlary:", left_margin, y, 7, bold=True)
    draw("//_______//_______//_______//_______//_______//____", left_margin + 55 * mm, y, 7)
    y -= 5 * mm
    for i in range(5):
        draw("Ady:", left_margin, y, 7, bold=True)
        draw_line(left_margin + 10 * mm, y - 0.5 * mm, content_w - 10 * mm)
        y -= 5 * mm

    y -= 2 * mm

    # --- Sargalan gerek bolan ätiýaçlyk şaýlary (ordered spare parts) ---
    draw("Sargalan gerek bolan ätiýaçlyk şaýlary:", left_margin, y, 7, bold=True)
    draw("________//________//________//________//________//", left_margin + 75 * mm, y, 7)
    y -= 5 * mm
    for i in range(6):
        draw("Ady:", left_margin, y, 7, bold=True)
        draw_line(left_margin + 10 * mm, y - 0.5 * mm, 100 * mm)
        draw("wagty", left_margin + 115 * mm, y, 7, bold=True)
        draw_line(left_margin + 125 * mm, y - 0.5 * mm, 30 * mm)
        y -= 5 * mm

    y -= 2 * mm

    # --- Düzedilen (Düzedilmedik) enjamyn görkezmesi ---
    draw("Düzedilen (Düzedilmedik) enjamyn görkezmesi:", left_margin, y, 7, bold=True)
    y -= 5 * mm
    draw_line(left_margin, y, content_w)
    y -= 5 * mm
    draw_line(left_margin, y, content_w)
    y -= 5 * mm

    y -= 2 * mm

    # --- Test / Kepillik ---
    draw("Test:", left_margin, y, 7, bold=True)
    draw_line(left_margin + 12 * mm, y - 0.5 * mm, 25 * mm)
    draw("//Kepillik", left_margin + 42 * mm, y, 7, bold=True)
    draw_line(left_margin + 65 * mm, y - 0.5 * mm, 40 * mm)
    y -= 6 * mm

    # --- Enjam tabşyryldy / Tölegi / kabul eden ---
    draw("Enjam tabşyryldy:", left_margin, y, 7, bold=True)
    draw_line(left_margin + 35 * mm, y - 0.5 * mm, 25 * mm)
    draw("Tölegi:", left_margin + 65 * mm, y, 7, bold=True)
    draw_line(left_margin + 78 * mm, y - 0.5 * mm, 20 * mm)
    draw("kabul eden:", left_margin + 105 * mm, y, 7, bold=True)
    draw_line(left_margin + 125 * mm, y - 0.5 * mm, 30 * mm)
    y -= 8 * mm

    # --- Footer ---
    draw_line(left_margin, y, content_w)
    y -= 5 * mm
    footer = t.get("footer") or "MSB — Мастер Сервис Бюро"
    draw(footer, w / 2, y, 6, color=(0.35, 0.35, 0.35), align="center")

    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Original render_blank_pdf (one-per-page / two-per-page)
# ---------------------------------------------------------------------------


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

    # Dispatch to Turkmen form
    if layout == "turkmen":
        return _render_turkmen_form(
            t=t, number=number, accepted_at=accepted_at, city_name=city_name,
            branch_name=branch_name, client_name=client_name, client_phone=client_phone,
            device=device, serial=serial, complectation=complectation,
            fault=fault, condition=condition, accepted_by=accepted_by,
            master=master, eta_days=eta_days, legal_text=legal_text,
            storage_until=storage_until, qr_url=qr_url,
            currency_symbol=currency_symbol,
            consent_repair_text=consent_repair_text,
            consent_repair=consent_repair,
        )

    copies = max(1, int(t.get("copies", 2) or 2))
    copy_labels = ["ЭКЗЕМПЛЯР КЛИЕНТА", "ЭКЗЕМПЛЯР СЕРВИСА"]

    brand = t.get("brand") or "MSB — Мастер Сервис Бюро"
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
