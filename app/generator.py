import os
import zipfile
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import letter

from app.config import PG13_TEMPLATE_PATH
from app.ship_matcher import match_ship


# Register Times New Roman
FONT_PATH = "/app/app/fonts/times.ttf"
pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_PATH))


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


def make_pg13_pdf(name, ship_raw, start, end, root_dir):
    output = os.path.join(root_dir, f"{ship_raw}.pdf")

    # Normalize ship name
    ship = match_ship(ship_raw)

    # Build text content
    line1 = f"REPORT CAREER SEA PAY FROM {format_mmddyy(start)} TO {format_mmddyy(end)}."
    line2 = f"Member performed eight continuous hours per day on-board: {ship} Category A vessel."

    # Exact coordinates converted to points
    def inches(x): return x * 72

    # Your coordinates (in inches)
    X1, Y1 = 0.91, 8.43
    X2, Y2 = 0.91, 8.08
    X_NAME, Y_NAME = 0.26, 0.63

    c = canvas.Canvas(output, pagesize=letter)

    # Draw template behind
    c.drawImage(PG13_TEMPLATE_PATH, 0, 0, width=letter[0], height=letter[1])

    # Font settings
    c.setFont("TimesNewRoman", 10)

    # Insert data at coordinates
    c.drawString(inches(X1), inches(11 - Y1), line1)
    c.drawString(inches(X2), inches(11 - Y2), line2)
    c.drawString(inches(X_NAME), inches(11 - Y_NAME), name)

    c.save()
    return output
