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

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter


# ------------------------------------------------
# HELPER: WRITE A SIMPLE TEXT-STYLE PDF FROM LINES
# ------------------------------------------------

def _write_pdf_from_lines(lines, pdf_path):
    """
    Render a list of text lines into a clean, readable PDF.
    Layout is simple and professional: Courier font, controlled wrap, page breaks.
    """
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter

    text = c.beginText(40, height - 40)
    text.setFont("Courier", 9)

    max_chars = 95      # wrap width
    line_spacing = 12   # not used directly; built into textLine step

    if not lines:
        lines = ["No validation data available."]

    for raw in lines:
        # Strip non-ASCII to avoid weird symbols in PDF
        clean = raw.encode("ascii", "ignore").decode()

        # Soft wrap long lines
        while len(clean) > max_chars:
            text.textLine(clean[:max_chars])
            clean = clean[max_chars:]

            # Handle page overflow
            if text.getY() < 40:
                c.drawText(text)
                c.showPage()
                text = c.beginText(40, height - 40)
                text.setFont("Courier", 9)

        text.textLine(clean)

        # Handle page overflow
        if text.getY() < 40:
            c.drawText(text)
            c.showPage()
            text = c.beginText(40, height - 40)
            text.setFont("Courier", 9)

    c.drawText(text)
    c.save()


# ------------------------------------------------
# PROFESSIONAL VALIDATION REPORTS (TXT + PDF)
# ------------------------------------------------

def write_validation_reports(summary_data):
    """
    Build professional validation reports directly from summary_data.

    Creates under OUTPUT_DIR/validation:
      - VALIDATION_REPORTS_MASTER.txt
      - VALIDATION_REPORTS_MASTER.pdf
      - VALIDATION_<RATE>_<LAST>_<FIRST>.txt  (per sailor)
      - VALIDATION_<RATE>_<LAST>_<FIRST>.pdf  (per sailor)
    """
    validation_dir = os.path.join(OUTPUT_DIR, "validation")
    os.makedirs(validation_dir, exist_ok=True)

    master_txt_path = os.path.join(validation_dir, "VALIDATION_REPORTS_MASTER.txt")
    master_pdf_path = os.path.join(validation_dir, "VALIDATION_REPORTS_MASTER.pdf")

    master_lines = []

    if not summary_data:
        # Nothing to report
        with open(master_txt_path, "w", encoding="utf-8") as f:
            f.write("No validation data available.\n")
        _write_pdf_from_lines(["No validation data available."], master_pdf_path)
        return

    # Sort sailors by LAST, FIRST for a clean order
    def sort_key(item):
        _key, sd = item
        return ((sd.get("last") or "").upper(), (sd.get("first") or "").upper())

    for key, sd in sorted(summary_data.items(), key=sort_key):
        rate = sd.get("rate") or ""
        last = sd.get("last") or ""
        first = sd.get("first") or ""
        display_name = f"{rate} {last}, {first}".strip()

        periods = sd.get("periods", []) or []
        skipped_unknown = sd.get("skipped_unknown", []) or []
        skipped_dupe = sd.get("skipped_dupe", []) or []

        total_days = sum(p.get("days", 0) for p in periods)

        # -----------------------------
        # Build per-sailor validation text
        # -----------------------------
        lines = []

        lines.append("=" * 69)
        lines.append(f"SAILOR: {display_name}")
        lines.append("=" * 69)
        lines.append("")

        # Summary block
        lines.append("SUMMARY")
        lines.append("-" * 69)
        lines.append(f"  Total Valid Sea Pay Days : {total_days}")
        lines.append(f"  Valid Period Count       : {len(periods)}")
        lines.append(f"  Invalid / Excluded Events: {len(skipped_unknown)}")
        lines.append(f"  Duplicate Date Conflicts : {len(skipped_dupe)}")
        lines.append("")

        # Valid periods
        lines.append("VALID SEA PAY PERIODS")
        lines.append("-" * 69)
        if periods:
            lines.append("  SHIP                START        END          DAYS")
            lines.append("  ------------------- ------------ ------------ ----")
            for p in periods:
                ship = (p.get("ship") or "").upper()
                start = p.get("start")
                end = p.get("end")
                days = p.get("days", 0)

                if hasattr(start, "strftime"):
                    start_str = start.strftime("%m/%d/%Y")
                else:
                    start_str = str(start)

                if hasattr(end, "strftime"):
                    end_str = end.strftime("%m/%d/%Y")
                else:
                    end_str = str(end)

                lines.append(
                    f"  {ship[:19]:19} {start_str:12} {end_str:12} {days:4}"
                )
        else:
            lines.append("  NONE")
        lines.append("")

        # Invalid / excluded events
        lines.append("INVALID / EXCLUDED EVENTS")
        lines.append("-" * 69)
        if skipped_unknown:
            for entry in skipped_unknown:
                date = entry.get("date", "UNKNOWN")
                ship = entry.get("ship") or entry.get("ship_name") or ""
                reason = entry.get("reason") or "Excluded / unrecognized / non-qualifying"
                detail = f"{date}"
                if ship:
                    detail += f" | {ship}"
                lines.append(f"  - {detail} — {reason}")
        else:
            lines.append("  NONE")
        lines.append("")

        # Duplicate date conflicts
        lines.append("DUPLICATE DATE CONFLICTS")
        lines.append("-" * 69)
        if skipped_dupe:
            for entry in skipped_dupe:
                date = entry.get("date", "UNKNOWN")
                ship = entry.get("ship") or entry.get("ship_name") or ""
                occ = entry.get("occ_idx") or entry.get("occurrence") or ""
                detail = f"{date}"
                if ship:
                    detail += f" | {ship}"
                if occ:
                    detail += f" | occurrence #{occ}"
                lines.append(f"  - {detail}")
        else:
            lines.append("  NONE")
        lines.append("")

        # Recommendations
        lines.append("RECOMMENDATIONS")
        lines.append("-" * 69)
        if skipped_unknown or skipped_dupe:
            lines.append("  - Review TORIS export for the dates listed above.")
            lines.append("  - Confirm ship names and event types against current guidance.")
            lines.append("  - Provide corrected certification sheet to ATG/PSD if required.")
        else:
            lines.append("  - No discrepancies detected based on current input.")
        lines.append("")
        lines.append("")

        # -----------------------------
        # Write per-sailor TXT + PDF
        # -----------------------------
        safe_name = f"{rate}_{last}_{first}".strip().replace(" ", "_").replace(",", "")
        if not safe_name:
            safe_name = key.replace(" ", "_").replace(",", "")

        sailor_txt_path = os.path.join(validation_dir, f"VALIDATION_{safe_name}.txt")
        sailor_pdf_path = os.path.join(validation_dir, f"VALIDATION_{safe_name}.pdf")

        with open(sailor_txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        _write_pdf_from_lines(lines, sailor_pdf_path)

        # Append to master
        master_lines.extend(lines)
        master_lines.append("=" * 69)
        master_lines.append("")

    # -----------------------------
    # Write master TXT + PDF
    # -----------------------------
    with open(master_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(master_lines))

    _write_pdf_from_lines(master_lines, master_pdf_path)


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

    # Write validation reports (TXT + per-sailor + master PDFs)
    write_validation_reports(summary_data)
    log("VALIDATION REPORTS UPDATED")

    log("✅ ALL OPERATIONS COMPLETE")
