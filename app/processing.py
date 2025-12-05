import os
import re
from datetime import datetime

from app.core.logger import log
from app.core.config import DATA_DIR, OUTPUT_DIR, SEA_PAY_PG13_FOLDER, TORIS_CERT_FOLDER
from app.core.ocr import ocr_pdf, strip_times, extract_member_name
from app.core.parser import parse_rows, extract_year_from_filename, group_by_ship
from app.core.pdf_writer import make_pdf_for_ship
from app.core.strikeout import mark_sheet_with_strikeouts
from app.core.merge import merge_all_pdfs
from app.core.summary import write_summary_files
from app.core.rates import resolve_identity

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black

# ... all your existing helper functions (date parsing, validation, ledger, trackers, etc.) remain unchanged ...


# ------------------------------------------------
# OUTPUT HELPERS
# ------------------------------------------------

def _clear_sea_pay_pg13_folder():
    """Remove all existing PG13 PDFs before a new run."""
    if not os.path.isdir(SEA_PAY_PG13_FOLDER):
        return
    for fname in os.listdir(SEA_PAY_PG13_FOLDER):
        fpath = os.path.join(SEA_PAY_PG13_FOLDER, fname)
        try:
            if os.path.isfile(fpath):
                os.remove(fpath)
        except Exception:
            # Do not fail the whole run if cleanup hits a locked file
            pass


# ------------------------------------------------
# MAIN PROCESSOR
# ------------------------------------------------

def process_all(strike_color="black"):
    _clear_sea_pay_pg13_folder()
    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]

    if not files:
        log("NO INPUT FILES")
        return

    log("=== PROCESS STARTED ===")
    summary_data = {}
    run_generated_at = datetime.now()

    for file in files:
        path = os.path.join(DATA_DIR, file)
        log(f"OCR → {file}")

        raw = strip_times(ocr_pdf(path))

        # Reporting period
        sheet_start, sheet_end, sheet_range_text = extract_reporting_period(raw, file)

        # Member name
        try:
            name = extract_member_name(raw)
            log(f"NAME → {name}")
        except Exception as e:
            log(f"NAME ERROR → {e}")
            continue

        # Parse TORIS rows
        year = extract_year_from_filename(file)
        rows, skipped_dupe, skipped_unknown = parse_rows(raw, year)

        # Group valid rows by ship
        groups = group_by_ship(rows)

        # Total days for this sheet
        total_days = sum((g["end"] - g["start"]).days + 1 for g in groups)

        # Identity
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
                "reporting_periods": [],
            }

        sd = summary_data[key]

        # Reporting window for this sheet
        sd["reporting_periods"].append({
            "start": sheet_start,
            "end": sheet_end,
            "file": file,
            "range_text": sheet_range_text,
        })

        # Valid periods
        for g in groups:
            days = (g["end"] - g["start"]).days + 1
            sd["periods"].append({
                "ship": g["ship"],
                "start": g["start"],
                "end": g["end"],
                "days": days,
                "sheet_start": sheet_start,
                "sheet_end": sheet_end,
                "sheet_file": file,
            })

        # Skipped
        sd["skipped_unknown"].extend(skipped_unknown)
        sd["skipped_dupe"].extend(skipped_dupe)

        # Strikeout TORIS Sea Pay Cert Sheet
        # Filename: <RATE>_<LAST>_<FIRST>__TORIS_SEA_DUTY_CERT_SHEETS__<FROM>_TO_<TO>.pdf
        if sheet_start and hasattr(sheet_start, "strftime"):
            header_from_str = sheet_start.strftime("%m-%d-%Y")
        else:
            header_from_str = "UNKNOWN"
        if sheet_end and hasattr(sheet_end, "strftime"):
            header_to_str = sheet_end.strftime("%m-%d-%Y")
        else:
            header_to_str = "UNKNOWN"

        base_name = (
            f"{rate}_{last}_{first}"
            f"__TORIS_SEA_DUTY_CERT_SHEETS__{header_from_str}_TO_{header_to_str}.pdf"
        )
        base_name = base_name.replace(" ", "_")
        marked_path = os.path.join(TORIS_CERT_FOLDER, base_name)

        mark_sheet_with_strikeouts(
            path,
            skipped_dupe,
            skipped_unknown,
            marked_path,
            total_days,
            strike_color=strike_color,
        )

        # Build NAVPERS PDFs by ship
        ship_periods = {
            g["ship"]: [] for g in groups
        }
        for g in groups:
            ship_periods[g["ship"]].append(g)

        for ship, periods in ship_periods.items():
            make_pdf_for_ship(ship, periods, name)

    # Merge NAVPERS PDFs + TORIS + SUMMARY into PACKAGE
    merge_all_pdfs()

    # Summary TXT/PDF (per member + master)
    write_summary_files(summary_data)

    # Validation, ledger, trackers, etc.
    write_validation_reports(summary_data)
    log("VALIDATION REPORTS DONE")

    write_validation_ledger(summary_data, run_generated_at)
    log("LEDGER DONE")

    write_json_tracker(summary_data, run_generated_at)
    write_csv_tracker(summary_data, run_generated_at)
    log("TRACKING DONE")

    log("✅ ALL OPERATIONS COMPLETE")
