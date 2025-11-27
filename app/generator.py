import os
import zipfile
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from PyPDF2 import PdfReader, PdfWriter, PageObject

from app.config import PG13_TEMPLATE_PATH
from app.ship_matcher import match_ship


# Register Times New Roman
FONT_PATH = "/app/app/fonts/times.ttf"
pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_PATH))


def format_mmddyy(date_obj):
    """Convert date to MM/DD/YY."""
    return date_obj.strftime("%m/%d/%y")


def inches_to_points(inches: float):
    """Convert inches to PDF points."""
    return inches * 72.0


# FINAL COORDINATES (confirmed from your mapping)
X_LINE1 = inches_to_points(0.50)   # REPORT CAREER SEA PAY...
Y_LINE1 = inches_to_points(8.375)

X_LINE2 = inches_to_points(0.50)   # Member performed eight hours...
Y_LINE2 = inches_to_points(8.125)

X_NAME = inches_to_points(0.63)    # NAME (LAST, FIRST, MIDDLE)
Y_NAME = inches_to_points(0.88)


def generate_pg13_zip(sailor, output_dir):
    """Create a ZIP containing one PG13 per ship event."""
    last = sailor["name"].split()[0].upper()
    zip_path = os.path.join(output_dir, f"{last}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for ship_raw, start, end in sailor["events"]:
            pdf_path = make_pg13_pdf(sailor["name"], ship_raw, start, end, output_dir)
            zf.write(pdf_path, os.path.basename(pdf_path))

    return zip_path


def make_pg13_pdf(name, ship_raw, start, end, root_dir):
    """Generate one completed NAVPERS 1070/613 with proper coordinates."""
    output_path = os.path.join(root_dir, f"{ship_raw}.pdf")

    # Clean ship name
    ship = match_ship(ship_raw)

    # Build text lines
    line1 = f"REPORT CAREER SEA PAY FROM {format_mmddyy(start)} TO {format_mmddyy(end)}."
    line2 = f"Member performed eight continuous hours per day on-board: {ship} Category A vessel."

    # Load template
    template_reader = PdfReader(PG13_TEMPLATE_PATH)
    template_page = template_reader.pages[0]

    # Create overlay PDF
    overlay_path = os.path.join(root_dir, "overlay.pdf")
    c = canvas.Canvas(overlay_path, pagesize=letter)

    # All fields use Times New Roman, size 10
    c.setFont("TimesNewRoman", 10)

    # Draw text at mapped coordinates
    c.drawString(X_LINE1, Y_LINE1, line1)
    c.drawString(X_LINE2, Y_LINE2, line2)
    c.drawString(X_NAME, Y_NAME, name)

    c.save()

    # Merge template + overlay
    overlay_reader = PdfReader(overlay_path)
    overlay_page = overlay_reader.pages[0]

    merged_page = PageObject.create_blank_page(
        width=template_page.mediabox.width,
        height=template_page.mediabox.height
    )
    merged_page.merge_page(template_page)
    merged_page.merge_page(overlay_page)

    writer = PdfWriter()
    writer.add_page(merged_page)

    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path
