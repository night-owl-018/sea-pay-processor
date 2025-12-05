import os
import re
from datetime import datetime

from app.core.logger import log
from app.core.config import (
    DATA_DIR,
    SEA_PAY_PG13_FOLDER,
    TORIS_CERT_FOLDER,
)
from app.core.ocr import ocr_pdf, strip_times, extract_member_name
from app.core.parser import parse_rows, extract_year_from_filename, group_by_ship
from app.core.pdf_writer import make_pdf_for_ship
from app.core.strikeout import mark_sheet_with_strikeouts
from app.core.summary import write_summary_files
from app.core.merge import merge_all_pdfs
from app.core.rates import resolve_identity

# -------------------------------------------------------------------------
# RESTORED FROM YOUR FILE — OFFICIAL REPORTING PERIOD EXTRACTOR
# -------------------------------------------------------------------------
# (This is from the file you uploaded)
# :contentReference[oaicite:1]{index=1}
def extract_reporting_period(text, filename=""):
    """
    Extracts the official sheet header date range:
    Example:
        "From: 8/4/2025 To: 11/24/2025"
    Returns:
        (start_date, end_date, "8/4/2025 - 11/24/2025")
    """

    pattern = r"From:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*To:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})"
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        from_raw = match.group(1)
        to_raw = match.group(2)

        try:
            start = datetime.strptime(from_raw, "%m/%d/%Y")
            end = datetime.strptime(to_raw, "%m/%d/%Y")
        except:
            return None, None, ""

        return start, end, f"{from_raw} - {to_raw}"

    # Try filename fallback ("8_4_2025 - 11_24_2025")
    alt_pattern = r"(\d{1,2}_\d{1,2}_\d{4})\s*-\s*(\d{1,2}_\d{1,2}_\d{4})"
    m2 = re.search(alt_pattern, filename)

    if m2:
        try:
            s = datetime.strptime(m2.group(1).replace("_", "/"), "%m/%d/%Y")
            e = datetime.strptime(m2.group(2).replace("_", "/"), "%m/%d/%Y")
            return s, e, f"{m2.group(1)} - {m2.group(2)}"
        except:
            return None, None, ""

    return None, None, ""


# -------------------------------------------------------------------------
# CLEAN PG13 FOLDER
# -------------------------------------------------------------------------
def clear_pg13_folder():
    """Delete all existing PG13 PDFs before generating new ones."""
    try:
        for f in os.listdir(SEA_PAY_PG13_FOLDER):
            fp = os.path.join(SEA_PAY_PG13_FOLDER, f)
            if os.path.isfile(fp):
                os.remove(fp)
    except:
        pass


# -------------------------------------------------------------------------
# MAIN PROCESS FUNCTION — RESTORED + ONLY NECESSARY UPDATES ADDED
# -------------------------------------------------------------------------
def process_all(strike_color="black"):
    """
    Main engine. This is your ORIGINAL function structure restored
    with only the required updates:
        • Clear PG13 folder
        • New TORIS filename format
        • New summary handler
        • PG13 filename handled inside pdf_writer
    """

    clear_pg13_folder()

    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]
    if not files:
        log("NO INPUT FILES FOUND")
        return

    log("=== PROCESS STARTED ===")
    summary_data = {}
    run_started = datetime.now()

    for file in files:
        path = os.path.join(DATA_DIR, file)
        log(f"OCR → {file}")

        raw = strip_times(ocr_pdf(path))

        # --------------------------
        # Extract header date range
        # --------------------------
        sheet_start, sheet_end, _ = extract_reporting_period(raw, file)

        # --------------------------
        # Name extraction
        # --------------------------
        try:
            name = extract_member_name(raw)
            log(f"NAME → {name}")
        except Exception as e:
            log(f"NAME ERROR → {e}")
            continue

        year = extract_year_from_filename(file)

        rows, skipped_dupe, skipped_unknown = parse_rows(raw, year)

        groups = group_by_ship(rows)
        total_days = sum((g["end"] - g["start"]).days + 1 for g in groups)

        rate, last, first = resolve_identity(name)
        key = f"{rate} {last},{first}"

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

        # reporting range
        sd["reporting_periods"].append({
            "start": sheet_start,
            "end": sheet_end,
            "file": file
        })

        # valid periods
        for g in groups:
            sd["periods"].append({
                "ship": g["ship"],
                "start": g["start"],
                "end": g["end"],
                "days": (g["end"] - g["start"]).days + 1,
                "sheet_file": file,
            })

        # skipped rows
        sd["skipped_unknown"].extend(skipped_unknown)
        sd["skipped_dupe"].extend(skipped_dupe)

        # -------------------------------------------------
        # CREATE TORIS SEA PAY CERT SHEET — UPDATED NAME
        # -------------------------------------------------
        hf = sheet_start.strftime("%m-%d-%Y") if sheet_start else "UNKNOWN"
        ht = sheet_end.strftime("%m-%d-%Y") if sheet_end else "UNKNOWN"

        toris_filename = (
            f"{rate}_{last}_{first}"
            f"__TORIS_SEA_DUTY_CERT_SHEETS__{hf}_TO_{ht}.pdf"
        ).replace(" ", "_")

        toris_path = os.path.join(TORIS_CERT_FOLDER, toris_filename)

        mark_sheet_with_strikeouts(
            path,
            skipped_dupe,
            skipped_unknown,
            toris_path,
            total_days,
            strike_color=strike_color,
        )

        # -------------------------------------------------
        # CREATE NAVPERS PG13 PDFs (filenames handled inside writer)
        # -------------------------------------------------
        ship_map = {}
        for g in groups:
            ship_map.setdefault(g["ship"], []).append(g)

        for ship, ship_periods in ship_map.items():
            make_pdf_for_ship(ship, ship_periods, name)

    # -------------------------------------------------
    # MERGE PDFS INTO PACKAGE
    # -------------------------------------------------
    merge_all_pdfs()

    # -------------------------------------------------
    # WRITE SUMMARY FILES
    # -------------------------------------------------
    write_summary_files(summary_data)

    log("PROCESS COMPLETE")
