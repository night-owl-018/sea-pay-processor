import os
import zipfile
import pdfplumber
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

from PyPDF2 import PdfReader, PdfWriter, PageObject

from app.config import PG13_TEMPLATE_PATH
from app.ship_matcher import match_ship


# Register Times New Roman
FONT_PATH = "/app/app/fonts/times.ttf"
pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_PATH))


def format_mmddyy(date_obj):
    return date_obj.strftime("%m/%d/%y")


def find_text_coordinates(pdf_path, target_text):
    """
    Search for specific visible text inside a PDF and return its (x, y) position.
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()

        for w in words:
            if target_text.lower() in w["text"].lower():
                return float(w["x0"]), float(w["top"])

    return None


def generate_pg13_zip(sailor, output_dir):
    last = sailor["name"].split()[0].upper()
    zip_path = os.path.join(output_dir, f"{last}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for ship_raw, start, end in sailor["events"]:
            pdf_path = make_pg13_pdf(sailor["name"], ship_raw, start, end, output_dir)
            zf.write(pdf_path, os.path.basename(pdf_path))

    return zip_path


def make_pg13_pdf(name, ship_raw, start, end, root_dir):
    """
    Replace text in exact PG-13 template positions by tracing the template itself.
    """
    output_path = os.path.join(root_dir, f"{ship_raw}.pdf")

    ship = match_ship(ship_raw)

    # Build replacement text
    line1 = f"REPORT CAREER SEA PAY FROM {format_mmddyy(start)} TO {format_mmddyy(end)}."
    line2 = f"Member performed eight continuous hours per day on-board: {ship} Category A vessel."

    # Extract text coordinates from template
    pos_line1 = find_text_coordinates(PG13_TEMPLATE_PATH, "REPORT CAREER SEA PAY FROM")
    pos_line2 = find_text_coordinates(PG13_TEMPLATE_PATH, "Member performed eight continuous hours per day")
    pos_name  = find_text_coordinates(PG13_TEMPLATE_PATH, "NAME (LAST, FIRST, MIDDLE)")

    if not (pos_line1 and pos_line2 and pos_name):
        raise Exception("Failed to locate anchor text in template PDF.")

    # Slight downward adjustment to avoid overlapping template text
    adj = 2  

    overlay_path = os.path.join(root_dir, "overlay.pdf")
    c = canvas.Canvas(overlay_path, pagesize=letter)
    c.setFont("TimesNewRoman", 10)

    # Draw at extracted positions
    c.drawString(pos_line1[0], letter[1] - pos_line1[1] - adj, line1)
    c.drawString(pos_line2[0], letter[1] - pos_line2[1] - adj, line2)
    c.drawString(pos_name[0],  letter[1] - pos_name[1] - adj, name)

    c.save()

    # Merge overlay with template
    template_reader = PdfReader(PG13_TEMPLATE_PATH)
    template_page = template_reader.pages[0]

    overlay_reader = PdfReader(overlay_path)
    overlay_page = overlay_reader.pages[0]

    merged = PageObject.create_blank_page(
        width=template_page.mediabox.width,
        height=template_page.mediabox.height,
    )
    merged.merge_page(template_page)
    merged.merge_page(overlay_page)

    writer = PdfWriter()
    writer.add_page(merged)

    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path
