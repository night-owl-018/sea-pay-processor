import io
from pathlib import Path
from datetime import datetime
from typing import List, Dict

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PyPDF2 import PdfReader, PdfWriter

from app.core.config import PG13_TEMPLATE, SEA_PAY_PG13_FOLDER
from app.core.logger import log
from app.core.rates import resolve_identity

FONT_NAME = "Times-Roman"
FONT_SIZE = 12


def _fmt_line_date(d: datetime) -> str:
    """MM/DD/YYYY for the sentence line."""
    return d.strftime("%m/%d/%Y")


def _fmt_file_date(d: datetime) -> str:
    """MM-DD-YYYY for filenames."""
    return d.strftime("%m-%d-%Y")


def flatten_pdf(overlay_buffer: io.BytesIO, output_path: Path) -> None:
    """
    Take an in-memory ReportLab page and flatten it onto the PG13 template.
    """
    overlay_buffer.seek(0)

    base_reader = PdfReader(str(PG13_TEMPLATE))
    overlay_reader = PdfReader(overlay_buffer)

    if not base_reader.pages or not overlay_reader.pages:
        raise ValueError("Template or overlay PDF has no pages")

    base_page = base_reader.pages[0]
    overlay_page = overlay_reader.pages[0]

    # Draw our overlay on top of the template
    base_page.merge_page(overlay_page)

    writer = PdfWriter()
    writer.add_page(base_page)

    SEA_PAY_PG13_FOLDER.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)


def make_pdf_for_ship(ship: str,
                      periods: List[Dict[str, datetime]],
                      member_name: str) -> None:
    """
    Create one NAVPERS 1070/613 for each contiguous valid sea-pay period
    on the given ship, using the original single-period sentence format:

      "____. REPORT CAREER SEA PAY FROM {START} TO {END}."
      "Member performed eight continuous hours per day on-board:
       {SHIP} Category A vessel."
    """
    if not periods:
        return

    SEA_PAY_PG13_FOLDER.mkdir(parents=True, exist_ok=True)

    rate, last, first = resolve_identity(member_name)

    # Clean up identity strings
    last = (last or "").strip()
    first = (first or "").strip()

    if rate:
        identity = f"{rate} {last}, {first}".strip().replace("  ", " ")
    else:
        identity = f"{last}, {first}".strip(", ").strip()

    ship_label = ship.strip()
    ship_for_filename = ship_label.upper().replace(" ", "_").replace(".", "")

    # Sort periods by start date so PDFs come out in time order
    sorted_periods = sorted(periods, key=lambda p: p["start"])

    for period in sorted_periods:
        start = period["start"]
        end = period["end"]

        start_line = _fmt_line_date(start)
        end_line = _fmt_line_date(end)

        start_file = _fmt_file_date(start)
        end_file = _fmt_file_date(end)

        filename = (
            f"{rate}_{last}_{first}"
            f"__SEA_PAY_PG13__{ship_for_filename}"
            f"__{start_file}_TO_{end_file}.pdf"
        ).replace("__", "_").strip("_")

        output_path = SEA_PAY_PG13_FOLDER / filename

        # Build the overlay page
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)

        # Station / header bits that actually change
        c.setFont(FONT_NAME, 10)
        # Ship / station line
        c.drawString(64, 705, "AFLOAT TRAINING GROUP SAN DIEGO (UIC. 49365)")

        # Permanent box "X"
        c.drawString(373, 671, "X")

        # Entitlement + authority
        c.drawString(64, 650, "ENTITLEMENT")
        c.setFont(FONT_NAME, 8)
        c.drawString(345, 641, "OPNAVINST 7220.14")

        # Main narrative text
        c.setFont(FONT_NAME, FONT_SIZE)
        y = 595

        # This is the line you showed in the screenshot
        line_1 = f"____. REPORT CAREER SEA PAY FROM {start_line} TO {end_line}."
        c.drawString(64, y, line_1)

        y -= 20
        line_2 = (
            f"Member performed eight continuous hours per day on-board: "
            f"{ship_label} Category A vessel."
        )
        c.drawString(90, y, line_2)

        # Signature captions (lines themselves are on the template)
        c.setFont(FONT_NAME, 10)
        c.drawString(330, 160, "Certifying Official & Date")
        c.drawString(330, 110, "FI MI Last Name")

        # Member identity in lower left
        c.setFont(FONT_NAME, FONT_SIZE)
        c.drawString(64, 110, identity)

        c.showPage()
        c.save()

        # Flatten overlay onto the NAVPERS template and write out
        flatten_pdf(buf, output_path)

        log(f"CREATED → {output_path.name}")
