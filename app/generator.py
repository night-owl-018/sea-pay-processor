import os
import zipfile
from datetime import datetime
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from app.config import PG13_TEMPLATE_PATH


def format_mmddyy(date_obj):
    return date_obj.strftime("%m/%d/%y")


def generate_pg13_zip(sailor, output_dir):
    last = sailor["name"].split()[0].upper()
    zip_path = os.path.join(output_dir, f"{last}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for ship, start, end in sailor["events"]:
            pdf_path = make_pg13_pdf(sailor["name"], ship, start, end, output_dir)
            zf.write(pdf_path, os.path.basename(pdf_path))

    return zip_path


def make_pg13_pdf(name, ship, start, end, root_dir):
    output_path = os.path.join(root_dir, f"{ship}.pdf")

    # Load template
    reader = PdfReader(PG13_TEMPLATE_PATH)
    template_page = reader.pages[0]

    # Temporary overlay PDF
    overlay_path = os.path.join(root_dir, "overlay.pdf")
    c = canvas.Canvas(overlay_path, pagesize=letter)

    # === COORDINATES (you can adjust these if needed) ===

    # Name field right under SHIP OR STATION:
    c.drawString(40 * mm, 245 * mm, name)

    # Subject field (example: "10/15/25 TO 10/25/25")
    date_range = f"{format_mmddyy(start)} TO {format_mmddyy(end)}"
    c.drawString(92 * mm, 233 * mm, date_range)

    # Entitlement box: ship name only (cleaned)
    c.drawString(40 * mm, 226 * mm, ship)

    # “REPORT CAREER SEA PAY FROM” line
    c.drawString(30 * mm, 212 * mm, f"{format_mmddyy(start)} TO {format_mmddyy(end)}")

    # Main body text (member performed…)
    c.drawString(20 * mm, 195 * mm,
                 f"Member performed eight continuous hours per day on-board: {ship} Category A vessel.")

    c.save()

    # Read overlay
    overlay_reader = PdfReader(overlay_path)
    overlay_page = overlay_reader.pages[0]

    # Merge overlay on top of template
    template_page.merge_page(overlay_page)

    # Write out final PDF
    writer = PdfWriter()
    writer.add_page(template_page)

    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path
