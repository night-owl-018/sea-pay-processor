import os
import io
import base64
from typing import Optional, Union
from PIL import Image
from datetime import datetime

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register Times New Roman TTF
pdfmetrics.registerFont(
    TTFont("TimesNewRoman", "/app/Times_New_Roman.ttf")
)

from app.core.logger import log
from app.core.config import (
    TEMPLATE,
    FONT_NAME,
    FONT_SIZE,
    SEA_PAY_PG13_FOLDER,
    get_certifying_officer_name,
    get_certifying_officer_name_pg13,
    get_certifying_date_yyyymmdd,
    get_signature_for_member_location
)
from app.core.rates import resolve_identity
from reportlab.lib.utils import ImageReader



# ------------------------------------------------
# DRAW SIGNATURE IMAGE ON CANVAS
# ------------------------------------------------
def _build_member_key(rate: str, last: str, first: str, name_fallback: str = "") -> str:
    """
    Build the member_key used across the app for signature lookup:
      "RATE LAST,FIRST"
    """
    rate = (rate or "").strip()
    last = (last or "").strip()
    first = (first or "").strip()

    if rate and last and first:
        return f"{rate} {last},{first}"
    if last and first:
        return f"{last},{first}"
    return (name_fallback or "").strip()


# ------------------------------------------------
# SIGNATURE HELPERS
# ------------------------------------------------

def _signature_to_pil(sig: Union[Image.Image, str, None]) -> Optional[Image.Image]:
    if sig is None:
        return None

    if isinstance(sig, Image.Image):
        return sig.convert("RGBA")

    if isinstance(sig, str):
        s = sig.strip()
        if not s:
            return None
        if "," in s:
            s = s.split(",", 1)[1]

        try:
            raw = base64.b64decode(s)
            img = Image.open(io.BytesIO(raw))
            return img.convert("RGBA")
        except Exception as e:
            log(f"SIGNATURE DECODE ERROR → {e}")
            return None

    return None


# ------------------------------------------------
# VECTOR SIGNATURE RENDERER
# ------------------------------------------------
def _draw_signature_vector(c, stroke_data, x, y, max_width=150, max_height=40):

    if not stroke_data:
        return False

    all_points = [pt for stroke in stroke_data for pt in stroke]
    if not all_points:
        return False

    min_x = min(pt["x"] for pt in all_points)
    max_x = max(pt["x"] for pt in all_points)
    min_y = min(pt["y"] for pt in all_points)
    max_y = max(pt["y"] for pt in all_points)

    width = max_x - min_x
    height = max_y - min_y

    if width <= 0 or height <= 0:
        return False

    scale = min(max_width / width, max_height / height)
    final_w = width * scale
    x_offset = (max_width - final_w) / 2.0

    c.saveState()
    c.translate(x + x_offset, y)
    c.scale(scale, scale)

    c.setLineCap(1)
    c.setLineJoin(1)
    c.setStrokeColor(black)

    for stroke in stroke_data:
        if len(stroke) < 2:
            continue
    
        path = c.beginPath()
    
        # Move to first point
        first = stroke[0]
        path.moveTo(first["x"] - min_x, first["y"] - min_y)
    
        # Smooth using quadratic-style midpoint interpolation
        for i in range(1, len(stroke) - 1):
            p0 = stroke[i]
            p1 = stroke[i + 1]
    
            mid_x = (p0["x"] + p1["x"]) / 2.0
            mid_y = (p0["y"] + p1["y"]) / 2.0
    
            path.curveTo(
                p0["x"] - min_x,
                p0["y"] - min_y,
                p0["x"] - min_x,
                p0["y"] - min_y,
                mid_x - min_x,
                mid_y - min_y
            )
    
        # Finish final segment
        last = stroke[-1]
        path.lineTo(last["x"] - min_x, last["y"] - min_y)
    
        avg_width = sum(pt.get("w", 2.0) for pt in stroke) / len(stroke)
        c.setLineWidth(avg_width)
        c.drawPath(path, stroke=1, fill=0)

    c.restoreState()
    return True


# ------------------------------------------------
# VECTOR-AWARE SIGNATURE DRAW
# ------------------------------------------------
def _draw_signature_image(
    c,
    sig_image,
    x,
    y,
    max_width=150,
    max_height=40,
    allow_upscale=True,
):

    # Try vector first
    if isinstance(sig_image, dict) and sig_image.get("stroke_data"):
        if _draw_signature_vector(
            c,
            sig_image["stroke_data"],
            x,
            y,
            max_width=max_width,
            max_height=max_height,
        ):
            return

    # PNG fallback
    sig_image_pil = _signature_to_pil(sig_image)
    if sig_image_pil is None:
        return

    orig_w, orig_h = sig_image_pil.size
    if not orig_w or not orig_h:
        return

    target_scale = 3
    sig_image_pil = sig_image_pil.resize(
        (orig_w * target_scale, orig_h * target_scale),
        Image.LANCZOS,
    )

    orig_w, orig_h = sig_image_pil.size

    scale = min(max_width / orig_w, max_height / orig_h)
    if not allow_upscale and scale > 1:
        scale = 1

    final_w = orig_w * scale
    final_h = orig_h * scale
    final_x = x + (max_width - final_w) / 2.0

    buf = io.BytesIO()
    sig_image_pil.save(buf, format="PNG")
    buf.seek(0)

    c.drawImage(
        ImageReader(buf),
        final_x,
        y,
        width=final_w,
        height=final_h,
        mask="auto"
    )

# ------------------------------------------------
# FLATTEN PDF  (UNCHANGED ORIGINAL)
# ------------------------------------------------
def flatten_pdf(path):
    try:
        reader = PdfReader(path)
        writer = PdfWriter()

        for page in reader.pages:
            if "/Annots" in page:
                del page["/Annots"]

            contents = page.get("/Contents")
            if isinstance(contents, list):
                merged = b""
                for obj in contents:
                    merged += obj.get_data()
                page["/Contents"] = writer._add_object(merged)

            if "/Rotate" in page:
                del page["/Rotate"]

            writer.add_page(page)

        if "/AcroForm" in writer._root_object:
            del writer._root_object["/AcroForm"]

        tmp = path + ".flat"
        with open(tmp, "wb") as f:
            writer.write(f)

        os.replace(tmp, path)
        log(f"FLATTENED → {os.path.basename(path)}")

    except Exception as e:
        log(f"⚠️ FLATTEN FAILED → {e}")


# ------------------------------------------------
# INTERNAL HELPER: Draw centered ing officer name
# ------------------------------------------------
def _draw_centered_certifying_officer(
    c,
    sig_line_left_x,
    sig_line_y,
    name,
    y_above_line=7.0,
    sig_line_text="_________________________",
    sig_line_font_size=8,
):
    """
    Centers `name` horizontally over the signature underline, and places it
    y_above_line points ABOVE the underline.
    """
    if not name:
        return

    # IMPORTANT: measure underline width using the SAME font size used to draw it
    sig_line_w = c.stringWidth(sig_line_text, FONT_NAME, sig_line_font_size)
    sig_mid_x = sig_line_left_x + (sig_line_w / 2.0)

    c.drawCentredString(sig_mid_x, sig_line_y + y_above_line, name)



# ------------------------------------------------
# INTERNAL HELPER: Draw PG-13 certifier DATE (YYYYMMDD)
# ------------------------------------------------
def _draw_pg13_certifier_date(c, date_yyyymmdd):
    """
    Draws the certifier date inside the PG-13 DATE box (format: YYYYMMDD).
    Coordinates are tuned for the NAVPERS 1070/613 template in pdf_template/.
    If your template shifts, adjust the X/Y below by a few points.
    """
    if not date_yyyymmdd:
        return

    # ✅ START HERE (template-aligned): tweak +/- 1–3 pts if needed
    date_center_x = 278.0  # DATE box next to SEA PAY CERTIFIER (tweak +/- 1–5)
    date_y = 81.5          # baseline aligned with SEA PAY CERTIFIER line (tweak +/- 1–3)

    c.setFont(FONT_NAME, 10)
    c.drawCentredString(date_center_x, date_y, date_yyyymmdd)

def _draw_pg13_verifying_official_signature(c, member_key):
    """
    Draws the verifying official signature inside the bottom-right
    'SIGNATURE OF VERIFYING OFFICIAL' box on the PG-13 template.
    ADJUSTED: Raised higher for better positioning in box.
    """
    sig_image = get_signature_for_member_location(member_key, 'pg13_verifying_official')
    if sig_image is None:
        return

    # Bottom-right signature box bounds
    box_left_x = 322.0
    box_right_x = 570.0
    # ADJUSTED: Raised UP 4 more pts (was 64.0, now 68.0)
    sig_bottom_y = 68.0

    _draw_signature_image(
        c,
        sig_image,
        x=box_left_x,
        y=sig_bottom_y,
        max_width=(box_right_x - box_left_x),
        max_height=30
    )



# ------------------------------------------------
# INTERNAL HELPER: Format YYYYMMDD -> MM/DD/YYYY
# ------------------------------------------------
def _fmt_mmddyyyy(date_yyyymmdd: str) -> str:
    if not date_yyyymmdd:
        return ""
    s = str(date_yyyymmdd).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[4:6]}/{s[6:8]}/{s[0:4]}"
    return s


# ------------------------------------------------
# 🔹 NEW: CONSOLIDATED ALL MISSIONS (ALL SHIPS ON ONE FORM)
# ------------------------------------------------
def make_consolidated_all_missions_pdf(
    ship_groups,
    name,
    overall_start=None,
    overall_end=None,
    rate=None,
    last=None,
    first=None,
):
    """
    Creates a SINGLE PG-13 form with ALL missions across ALL ships for a member.
    Filename date range uses OVERALL SHEET reporting range when provided.
    """

    if not ship_groups:
        return

    # Prefer explicit identity from processing (prevents broken "_C_STG1..." prefixes)
    if not (rate and last and first):
        rate, last, first = resolve_identity(name)

    # Per-member signatures use the member_key (RATE LAST,FIRST) as the lookup key.
    member_key = _build_member_key(rate, last, first, name_fallback=name)

    # Sort ships alphabetically for consistency
    sorted_ships = sorted(ship_groups.items())

    # Calculate total periods across all ships
    total_periods = sum(len(periods) for _, periods in sorted_ships)

    # Collect all periods (for content ordering)
    all_periods = []
    for _, periods in sorted_ships:
        all_periods.extend(periods)

    if not all_periods:
        return

    # Choose filename date range:
    # - If overall_start/overall_end are given -> use those (sheet range)
    # - Else -> fall back to first/last mission period
    if overall_start and overall_end:
        s_fn = overall_start.strftime("%m-%d-%Y")
        e_fn = overall_end.strftime("%m-%d-%Y")
    else:
        all_periods_sorted = sorted(all_periods, key=lambda g: g["start"])
        first_period = all_periods_sorted[0]
        last_period = all_periods_sorted[-1]
        s_fn = first_period["start"].strftime("%m-%d-%Y")
        e_fn = last_period["end"].strftime("%m-%d-%Y")

    # ✅ Desired prefix format: "STG1_HATTEN,FRANK__..."
    prefix = f"{rate}_{last},{first}" if rate else f"{last},{first}"
    filename = f"{prefix}__PG13__ALL_MISSIONS__{s_fn}_TO_{e_fn}.pdf"
    filename = filename.replace(" ", "_")

    outpath = os.path.join(SEA_PAY_PG13_FOLDER, filename)

    # Create overlay with all ships and their periods
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont(FONT_NAME, FONT_SIZE)

    # HEADER BLOCK
    c.drawString(39, 689, "AFLOAT TRAINING GROUP SAN DIEGO (UIC. 49365)")
    c.drawString(373, 671, "X")
    c.setFont(FONT_NAME, 8)
    c.drawString(39, 650, "ENTITLEMENT")
    c.drawString(345, 641, "OPNAVINST 7220.14")

    # Member identity
    c.setFont(FONT_NAME, 11)
    identity = f"{rate} {last}, {first}" if rate else f"{last}, {first}"
    c.drawString(39, 41, identity)

    # MAIN TEXT BLOCK - ALL SHIPS AND PERIODS
    # Mission event lines must match NAVPERS template (10pt)
    c.setFont(FONT_NAME, 10)

    y = 595
    line_spacing = 12
    current_line = 0

    for ship, periods in sorted_ships:
        periods_sorted = sorted(periods, key=lambda g: g["start"])

        for g in periods_sorted:
            s = g["start"].strftime("%m/%d/%Y")
            e = g["end"].strftime("%m/%d/%Y")

            c.drawString(
                38.8,
                y - (current_line * line_spacing),
                f"____. REPORT CAREER SEA PAY FROM {s} TO {e}."
            )
            current_line += 1

        c.drawString(
            64,
            y - (current_line * line_spacing),
            f"Member performed eight continuous hours per day on-board: "
            f"{ship.upper()} Category A vessel."
        )
        current_line += 1

        if ship != sorted_ships[-1][0]:
            current_line += 1

    # SIGNATURE AREAS
    content_height = current_line * line_spacing
    base_sig_y = 499.5
    sig_y = min(base_sig_y, 595 - content_height - 40)

    sig_left_x = 356.26
    sig_line_text = "____________________________________"
    sig_line_font_size = 8

    # Calculate center from underline width (same font size used to draw it)
    sig_line_w = c.stringWidth(sig_line_text, FONT_NAME, sig_line_font_size)
    sig_mid_x = sig_left_x + (sig_line_w / 2.0)

    c.setFont(FONT_NAME, sig_line_font_size)
    c.drawString(sig_left_x, sig_y, sig_line_text)
    c.setFont(FONT_NAME, 10)

    # Date aligned to right edge of underline (MM/DD/YYYY)
    sig_date = _fmt_mmddyyyy(get_certifying_date_yyyymmdd())
    if sig_date:
        c.setFont(FONT_NAME, 10)
        sig_right_x = sig_left_x + sig_line_w
        date_w = c.stringWidth(sig_date, FONT_NAME, 10)
        c.drawString(sig_right_x - date_w, sig_y + 2, sig_date)
    c.setFont(FONT_NAME, 10)
    c.drawCentredString(sig_mid_x, sig_y - 12, "Certifying Official & Date")

    # NEW: Draw CERTIFYING OFFICIAL signature at same height as date
    sig_image = get_signature_for_member_location(member_key, 'pg13_certifying_official')
    if sig_image is not None:
        # ADJUSTED: Lower signature DOWN for better positioning
        sig_bottom_y = sig_y - 2  # Lowered DOWN 4pts (was +2, now -2)
        _draw_signature_image(
            c,
            sig_image,
            sig_left_x - 10,
            sig_bottom_y,
            max_width=170,
            max_height=35
        )

    # Tighten vertical spacing (was sig_y - 72, too large)
    bottom_line_y = sig_y - 52
    c.setFont(FONT_NAME, sig_line_font_size)

    c.drawString(sig_left_x, bottom_line_y, sig_line_text)

    # ✅ Certifying officer name centered over underline
    c.setFont(FONT_NAME, 11)
    certifying_officer_name = get_certifying_officer_name_pg13()
    _draw_centered_certifying_officer(
        c,
        sig_left_x,
        bottom_line_y,
        certifying_officer_name,
        y_above_line=7.0,
        sig_line_text=sig_line_text,
        sig_line_font_size=sig_line_font_size,
    )

    # FI MI Last Name centered under underline
    c.setFont(FONT_NAME, 10)
    c.drawCentredString(sig_mid_x, bottom_line_y - 12.3, "FI MI Last Name")
    # NOTE: PG-13 member signature disabled (user requested nothing above the member name line)

    c.setFont(FONT_NAME, 10)
    c.drawString(38.8, 83, "SEA PAY CERTIFIER")
    c.drawString(503.5, 40, "USN AD")

    # ✅ PG-13 DATE box (YYYYMMDD)
    _draw_pg13_certifier_date(c, get_certifying_date_yyyymmdd())

    # ✅ PG-13 verifying official signature (bottom-right box)
    _draw_pg13_verifying_official_signature(c, member_key)

    c.save()
    buf.seek(0)

    # MERGE WITH TEMPLATE
    template = PdfReader(TEMPLATE)
    overlay = PdfReader(buf)
    base = template.pages[0]
    base.merge_page(overlay.pages[0])

    writer = PdfWriter()
    writer.add_page(base)

    with open(outpath, "wb") as f:
        writer.write(f)

    flatten_pdf(outpath)

    ship_count = len(sorted_ships)
    log(f"CREATED ALL MISSIONS PG-13 → {filename} ({ship_count} ships, {total_periods} periods on 1 form)")


# ------------------------------------------------
# 🔹 NEW: CONSOLIDATED PG-13 (MULTIPLE PERIODS ON ONE FORM)
# ------------------------------------------------
def make_consolidated_pdf_for_ship(ship, periods, name):
    if not periods:
        return

    rate, last, first = resolve_identity(name)
    member_key = _build_member_key(rate, last, first, name_fallback=name)
    periods_sorted = sorted(periods, key=lambda g: g["start"])

    first_period = periods_sorted[0]
    last_period = periods_sorted[-1]

    s_fn = first_period["start"].strftime("%m-%d-%Y")
    e_fn = last_period["end"].strftime("%m-%d-%Y")

    filename = (
        f"{rate}_{last}_{first}"
        f"__SEA_PAY_PG13__{ship.upper()}__CONSOLIDATED__{s_fn}_TO_{e_fn}.pdf"
    )
    filename = filename.replace(" ", "_")

    outpath = os.path.join(SEA_PAY_PG13_FOLDER, filename)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont(FONT_NAME, FONT_SIZE)

    c.drawString(39, 689, "AFLOAT TRAINING GROUP SAN DIEGO (UIC. 49365)")
    c.drawString(373, 671, "X")
    c.setFont(FONT_NAME, 8)
    c.drawString(39, 650, "ENTITLEMENT")
    c.drawString(345, 641, "OPNAVINST 7220.14")

    c.setFont(FONT_NAME, 11)
    identity = f"{rate} {last}, {first}" if rate else f"{last}, {first}"
    c.drawString(39, 41, identity)

    # Mission event lines must match NAVPERS template (10pt)
    c.setFont(FONT_NAME, 10)

    y = 595
    line_spacing = 12

    for idx, g in enumerate(periods_sorted):
        s = g["start"].strftime("%m/%d/%Y")
        e = g["end"].strftime("%m/%d/%Y")
        c.drawString(38.8, y - (idx * line_spacing),
                    f"____. REPORT CAREER SEA PAY FROM {s} TO {e}.")

    ship_line_y = y - (len(periods_sorted) * line_spacing) - 12
    c.drawString(
        64,
        ship_line_y,
        f"Member performed eight continuous hours per day on-board: "
        f"{ship.upper()} Category A vessel."
    )

    sig_left_x = 356.26
    top_sig_y = 499.5
    bottom_line_y = 427.5

    sig_line_text = "____________________________________"
    sig_line_font_size = 8
    sig_line_w = c.stringWidth(sig_line_text, FONT_NAME, sig_line_font_size)
    sig_mid_x = sig_left_x + (sig_line_w / 2.0)

    c.setFont(FONT_NAME, sig_line_font_size)
    c.drawString(sig_left_x, top_sig_y, sig_line_text)
    c.setFont(FONT_NAME, 10)

    # Date aligned to right edge of underline (MM/DD/YYYY)
    sig_date = _fmt_mmddyyyy(get_certifying_date_yyyymmdd())
    if sig_date:
        c.setFont(FONT_NAME, 10)
        sig_right_x = sig_left_x + sig_line_w
        date_w = c.stringWidth(sig_date, FONT_NAME, 10)
        c.drawString(sig_right_x - date_w, top_sig_y + 2, sig_date)
    c.setFont(FONT_NAME, 10)
    c.drawCentredString(sig_mid_x, top_sig_y - 12, "Certifying Official & Date")
    
    # NEW: Draw CERTIFYING OFFICIAL signature at same height as date
    sig_image = get_signature_for_member_location(member_key, 'pg13_certifying_official')
    if sig_image is not None:
        sig_bottom_y = top_sig_y - 2  # ADJUSTED: Lowered DOWN
        _draw_signature_image(c, sig_image, sig_left_x - 10, sig_bottom_y, max_width=170, max_height=35)
    
    c.setFont(FONT_NAME, sig_line_font_size)

    c.drawString(sig_left_x, bottom_line_y, sig_line_text)

    # ✅ Certifying officer name centered + lower
    c.setFont(FONT_NAME, 11)
    certifying_officer_name = get_certifying_officer_name_pg13()
    _draw_centered_certifying_officer(
        c,
        sig_left_x,
        bottom_line_y,
        certifying_officer_name,
        y_above_line=7.0,
        sig_line_text=sig_line_text,
        sig_line_font_size=sig_line_font_size,
    )

    # FI MI Last Name centered
    c.setFont(FONT_NAME, 10)
    c.drawCentredString(sig_mid_x, bottom_line_y - 12.3, "FI MI Last Name")
    # NOTE: PG-13 member signature disabled (user requested nothing above the member name line)

    c.setFont(FONT_NAME, 10)
    c.drawString(38.8, 83, "SEA PAY CERTIFIER")
    c.drawString(503.5, 40, "USN AD")

    # ✅ PG-13 DATE box (YYYYMMDD)
    _draw_pg13_certifier_date(c, get_certifying_date_yyyymmdd())

    # ✅ PG-13 verifying official signature (bottom-right box)
    _draw_pg13_verifying_official_signature(c, member_key)

    c.save()
    buf.seek(0)

    template = PdfReader(TEMPLATE)
    overlay = PdfReader(buf)
    base = template.pages[0]
    base.merge_page(overlay.pages[0])

    writer = PdfWriter()
    writer.add_page(base)

    with open(outpath, "wb") as f:
        writer.write(f)

    flatten_pdf(outpath)

    total_periods = len(periods_sorted)
    log(f"CREATED CONSOLIDATED PG-13 → {filename} ({total_periods} periods on 1 form)")


# ------------------------------------------------
# ORIGINAL FORMAT — ONE PG-13 PER PERIOD
# ------------------------------------------------
def make_pdf_for_ship(ship, periods, name, consolidate=False):
    if not periods:
        return

    if consolidate and len(periods) > 1:
        make_consolidated_pdf_for_ship(ship, periods, name)
        return

    rate, last, first = resolve_identity(name)
    member_key = _build_member_key(rate, last, first, name_fallback=name)
    periods_sorted = sorted(periods, key=lambda g: g["start"])

    for g in periods_sorted:
        s = g["start"].strftime("%m/%d/%Y")
        e = g["end"].strftime("%m/%d/%Y")

        s_fn = s.replace("/", "-")
        e_fn = e.replace("/", "-")

        filename = (
            f"{rate}_{last}_{first}"
            f"__SEA_PAY_PG13__{ship.upper()}__{s_fn}_TO_{e_fn}.pdf"
        )
        filename = filename.replace(" ", "_")

        outpath = os.path.join(SEA_PAY_PG13_FOLDER, filename)

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.setFont(FONT_NAME, FONT_SIZE)

        c.drawString(39, 689, "AFLOAT TRAINING GROUP SAN DIEGO (UIC. 49365)")
        c.drawString(373, 671, "X")
        c.setFont(FONT_NAME, 8)
        c.drawString(39, 650, "ENTITLEMENT")
        c.drawString(345, 641, "OPNAVINST 7220.14")

        c.setFont(FONT_NAME, 11)
        identity = f"{rate} {last}, {first}" if rate else f"{last}, {first}"
        c.drawString(39, 41, identity)

        # Mission event lines must match NAVPERS template (10pt)
        c.setFont(FONT_NAME, 10)

        y = 595
        c.drawString(38.8, y, f"____. REPORT CAREER SEA PAY FROM {s} TO {e}.")

        c.drawString(
            64,
            y - 24,
            f"Member performed eight continuous hours per day on-board: "
            f"{ship.upper()} Category A vessel."
        )

        sig_left_x = 356.26
        top_sig_y = 499.5
        bottom_line_y = 427.5

        sig_line_text = "____________________________________"
        sig_line_font_size = 8
        sig_line_w = c.stringWidth(sig_line_text, FONT_NAME, sig_line_font_size)
        sig_mid_x = sig_left_x + (sig_line_w / 2.0)

        c.setFont(FONT_NAME, sig_line_font_size)
        c.drawString(sig_left_x, top_sig_y, sig_line_text)
        c.setFont(FONT_NAME, 10)

        # Date aligned to right edge of underline (MM/DD/YYYY)
        sig_date = _fmt_mmddyyyy(get_certifying_date_yyyymmdd())
        if sig_date:
            c.setFont(FONT_NAME, 10)
            sig_right_x = sig_left_x + sig_line_w
            date_w = c.stringWidth(sig_date, FONT_NAME, 10)
            c.drawString(sig_right_x - date_w, top_sig_y + 2, sig_date)
        c.setFont(FONT_NAME, 10)
        c.drawCentredString(sig_mid_x, top_sig_y - 12, "Certifying Official & Date")
        
        # NEW: Draw CERTIFYING OFFICIAL signature at same height as date
        sig_image = get_signature_for_member_location(member_key, 'pg13_certifying_official')
        if sig_image is not None:
            sig_bottom_y = top_sig_y - 2  # ADJUSTED: Lowered DOWN
            _draw_signature_image(c, sig_image, sig_left_x - 10, sig_bottom_y, max_width=170, max_height=35)
        
        c.setFont(FONT_NAME, sig_line_font_size)

        c.drawString(sig_left_x, bottom_line_y, sig_line_text)

        # ✅ Certifying officer name centered + lower
        c.setFont(FONT_NAME, 11)
        certifying_officer_name = get_certifying_officer_name_pg13()
        _draw_centered_certifying_officer(
            c,
            sig_left_x,
            bottom_line_y,
            certifying_officer_name,
            y_above_line=7.0,
            sig_line_text=sig_line_text,
            sig_line_font_size=sig_line_font_size,
        )

        # FI MI Last Name centered
        c.setFont(FONT_NAME, 10)
        c.drawCentredString(sig_mid_x, bottom_line_y - 12.3, "FI MI Last Name")
        # NOTE: PG-13 member signature disabled (user requested nothing above the member name line)
        
        c.setFont(FONT_NAME, 10)
        c.drawString(38.8, 83, "SEA PAY CERTIFIER")
        c.drawString(503.5, 40, "USN AD")

        # ✅ PG-13 DATE box (YYYYMMDD)
        _draw_pg13_certifier_date(c, get_certifying_date_yyyymmdd())

        # ✅ PG-13 verifying official signature (bottom-right box)
        _draw_pg13_verifying_official_signature(c, member_key)

        c.save()
        buf.seek(0)

        template = PdfReader(TEMPLATE)
        overlay = PdfReader(buf)
        base = template.pages[0]
        base.merge_page(overlay.pages[0])

        writer = PdfWriter()
        writer.add_page(base)

        with open(outpath, "wb") as f:
            writer.write(f)

        flatten_pdf(outpath)
        log(f"CREATED → {filename}")
