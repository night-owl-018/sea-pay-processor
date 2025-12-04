import os
from datetime import datetime, timedelta

from app.core.logger import log
from app.core.config import DATA_DIR, OUTPUT_DIR
from app.core.ocr import ocr_pdf, strip_times, extract_member_name
from app.core.parser import parse_rows, extract_year_from_filename, group_by_ship
from app.core.pdf_writer import make_pdf_for_ship
from app.core.strikeout import mark_sheet_with_strikeouts
from app.core.merge import merge_all_pdfs
from app.core.summary import write_summary_files
from app.core.rates import resolve_identity

# ------------------------------------------------
# VALIDATION REPORT BUILDER  (TXT + PDF)
# ------------------------------------------------

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter


def write_validation_reports_from_summaries():
    """
    Build validation reports (TXT + PDF) from summary text files.
    Output:
      /output/validation/VALIDATION_REPORTS.txt
      /output/validation/VALIDATION_REPORTS.pdf
    """
    summary_dir = os.path.join(OUTPUT_DIR, "summary")
    validation_dir = os.path.join(OUTPUT_DIR, "validation")

    os.makedirs(validation_dir, exist_ok=True)

    combined_txt_path = os.path.join(validation_dir, "VALIDATION_REPORTS.txt")
    combined_pdf_path = os.path.join(validation_dir, "VALIDATION_REPORTS.pdf")

    lines = []

    if os.path.exists(summary_dir):
        for fname in sorted(os.listdir(summary_dir)):
            if fname.lower().endswith(".txt"):
                full_path = os.path.join(summary_dir, fname)

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read().strip()
                except Exception:
                    content = "[ERROR READING SUMMARY FILE]"

                lines.append(f"===== {fname} =====")
                lines.append(content)
                lines.append("")  # blank line between sailors

    # ------------------------
    # Write TXT report
    # ------------------------
    if lines:
        txt_output = "\n".join(lines)
    else:
        txt_output = "No validation data found.\n"

    with open(combined_txt_path, "w", encoding="utf-8") as f:
        f.write(txt_output)

    # ------------------------
    # Write PDF report
    # ------------------------
    c = canvas.Canvas(combined_pdf_path, pagesize=letter)
    width, height = letter
    x = 40
    y = height - 40
    line_spacing = 12
    max_len = 110  # crude wrap width

    if not lines:
        c.drawString(x, y, "No validation data found.")
    else:
        for raw in lines:
            line = raw
            # wrap long lines
            while len(line) > max_len:
                chunk = line[:max_len]
                if y < 40:
                    c.showPage()
                    y = height - 40
                c.drawString(x, y, chunk)
                y -= line_spacing
                line = line[max_len:]
            # final fragment
            if y < 40:
                c.showPage()
                y = height - 40
            c.drawString(x, y, line)
            y -= line_spacing

    c.save()


# ------------------------------------------------
# PROCESS ALL PDFs
# ------------------------------------------------

def process_all(strike_color="black"):
    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]

    if not files:
        log("NO INPUT FILES")
        return

    log("=== PROCESS STARTED ===")

    summary_data = {}

    for file in files:
        log(f"OCR → {file}")
        path = os.path.join(DATA_DIR, file)

        # OCR
        raw = strip_times(ocr_pdf(path))

        # Extract Name
        try:
            name = extract_member_name(raw)
            log(f"NAME → {name}")
        except Exception as e:
            log(f"NAME ERROR → {e}")
            continue

        # Parse rows into valid/invalid groups
        year = extract_year_from_filename(file)
        rows, skipped_dupe, skipped_unknown = parse_rows(raw, year)

        # Group valid periods by ship
        groups = group_by_ship(rows)

        # Compute total valid days (for total-days correction)
        total_days = sum(
            (g["end"] - g["start"]).days + 1
            for g in groups
        )

        # Strikeout marked sheet
        marked_dir = os.path.join(OUTPUT_DIR, "marked_sheets")
        os.makedirs(marked_dir, exist_ok=True)
        marked_path = os.path.join(marked_dir, f"MARKED_{os.path.splitext(file)[0]}.pdf")

        mark_sheet_with_strikeouts(
            path,
            skipped_dupe,
            skipped_unknown,
            marked_path,
            total_days,
            strike_color=strike_color,
        )

        # Create 1070 PDFs for each ship
        ship_periods = {}
        for g in groups:
            ship_periods.setdefault(g["ship"], []).append(g)

        for ship, periods in ship_periods.items():
            make_pdf_for_ship(ship, periods, name)

        # Prepare summary data for this sailor
        rate, last, first = resolve_identity(name)
        key = f"{rate} {last},{first}" if rate else f"{last},{first}"

        if key not in summary_data:
            summary_data[key] = {
                "rate": rate,
                "last": last,
                "first": first,
                "periods": [],
                "skipped_unknown": [],
                "skipped_dupe": [],
            }

        sd = summary_data[key]

        # Add valid grouped periods
        for g in groups:
            days = (g["end"] - g["start"]).days + 1
            sd["periods"].append({
                "ship": g["ship"],
                "start": g["start"],
                "end": g["end"],
                "days": days,
            })

        # Add invalid/skipped entries
        sd["skipped_unknown"].extend(skipped_unknown)
        sd["skipped_dupe"].extend(skipped_dupe)

    # Merge all PDFs into one
    merge_all_pdfs()

    # Write summary text files
    write_summary_files(summary_data)

    # ------------------------------------------------
    # ⭐ NEW: Write Validation Reports (TXT + PDF)
    # ------------------------------------------------
    write_validation_reports_from_summaries()
    log("VALIDATION REPORTS UPDATED")

    log("✅ ALL OPERATIONS COMPLETE")
