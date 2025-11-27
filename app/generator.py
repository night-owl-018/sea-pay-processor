import os
import zipfile
from datetime import datetime
from pypdf import PdfReader, PdfWriter, PageObject
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from app.config import PG13_TEMPLATE_PATH

# Register Times New Roman
FONT_PATH = "/app/app/fonts/times.ttf"
pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_PATH))

# Convert sailor date into MM/DD/YY format
def format_mmddyy(date_obj):
    return date_obj.strftime("%m/%d/%y")


def generate_pg13_zip(sailor, output_dir):
    last = sailor["name"].split()[0].upper()
    zip_path = os.path.join(output_dir, f"{last}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for ship, start, end in sailor["events"]:
            pdf_path = make_pg13_pdf(
                name=sailor["name"],
                ship=ship,
                start=start,
                end=end,
                root_dir=output_dir
            )
            zf.write(pdf_path, os.path.basename(pdf_path))

    return zip_path


def make_pg13_pdf(name, ship, start, end, root_dir):
    output_path = os.path.join(root_dir, f"{ship}.pdf")

    # Load the template
    reader = PdfReader(PG13_TEMPLATE_PATH)
    base_page = reader.pages[0]

    # Create an overlay PDF with ReportLab
    overlay_path = os.path.join(root_dir, "overlay.pdf")
    c = canvas.Canvas(overlay_path, pagesize=letter)

    c.setFont("TimesNewRoman", 10)

    # Convert sailor name to LAST, FIRST format
    name_parts = name.split()
    last = name_parts[-1].upper()
    first = name_parts[0].upper()
    middle = " ".join(name_parts[1:-1]).upper() if len(name_parts) > 2 else ""
    formatted_name = f"{last}, {first}" + (f" {middle}" if middle else "")

    # Format text blocks
    date_range = f"{format_mmddyy(start)} TO {format_mmddyy(end)}"
    line1 = f"REPORT CAREER SEA PAY FROM {date_range}."
    line2 = f"Member performed eight continuous hours per day on-board: {ship} Category A vessel."

    # Draw text at specified coordinates
    c.drawString(65.52, 606.96, line1)     # Header line
    c.drawString(65.52, 581.76, line2)     # Statement
    c.drawString(18.72, 45.36, formatted_name)  # Name field

    c.save()

    # Merge overlay with the template
    overlay_pdf = PdfReader(overlay_path)
    overlay_page = overlay_pdf.pages[0]

    merged = PageObject.create_blank_page(width=base_page.mediabox.width,
                                          height=base_page.mediabox.height)
    merged.merge_page(base_page)
    merged.merge_page(overlay_page)

    # Write final result
    writer = PdfWriter()
    writer.add_page(merged)

    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path
