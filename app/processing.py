import os
import json
from datetime import datetime

from app.core.logger import log
from app.core.config import (
    DATA_DIR,
    OUTPUT_DIR,
    SEA_PAY_PG13_FOLDER,
    TORIS_CERT_FOLDER,
    SUMMARY_TXT_FOLDER,
    SUMMARY_PDF_FOLDER,
    TRACKER_FOLDER,
)
from app.core.ocr import extract_text
from app.core.rates import resolve_identity
from app.core.parser import parse_rows
from app.core.toris import mark_sheet_with_strikeouts
from app.core.pdf_writer import make_pdf_for_ship
from app.core.summary import write_summary_files
from app.core.merge import merge_all_pdfs


# -------------------------------------------------------------------------
# Build summary data structure
# -------------------------------------------------------------------------
def build_summary_dict(name, rate, first, last):
    return {
        "rate": rate,
        "first": first,
        "last": last,
        "periods": [],
        "skipped_unknown": [],
        "skipped_dupe": [],
        "reporting_periods": []
    }


# -------------------------------------------------------------------------
# Ensure folder structure exists
# -------------------------------------------------------------------------
def ensure_directories():
    for folder in [
        SEA_PAY_PG13_FOLDER,
        TORIS_CERT_FOLDER,
        SUMMARY_TXT_FOLDER,
        SUMMARY_PDF_FOLDER,
        TRACKER_FOLDER,
    ]:
        os.makedirs(folder, exist_ok=True)


# -------------------------------------------------------------------------
# Main processor
# -------------------------------------------------------------------------
def process_all(strike_color="black"):

    ensure_directories()

    log("=== PROCESS STARTED ===")

    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]
    if not files:
        log("No PDF files found in incoming folder.")
        return

    summary_data = {}

    for file in sorted(files):
        path = os.path.join(DATA_DIR, file)

        # -----------------------------------------------------
        # STEP 1: OCR
        # -----------------------------------------------------
        log(f"OCR → {file}")
        raw_text = extract_text(path)

        # -----------------------------------------------------
        # STEP 2: Identify Sailor
        # -----------------------------------------------------
        name = resolve_identity(raw_text)
        if not name:
            log("Could not identify member from OCR; skipping file.")
            continue

        rate, last, first = name
        full_key = f"{last},{first}"

        log(f"NAME → {first} {last}")
        log(f"CSV MATCH (1.00) → {rate} {last},{first}")

        # Init summary entry
        if full_key not in summary_data:
            summary_data[full_key] = build_summary_dict(file, rate, first, last)

        # -----------------------------------------------------
        # STEP 3: Parse TORIS table rows
        # -----------------------------------------------------
        rows = parse_rows(raw_text)

        # Store reporting period min/max for summary header
        if rows:
            s_dates = [r["date"] for r in rows if r.get("date")]
            if s_dates:
                summary_data[full_key]["reporting_periods"].append({
                    "start": min(s_dates),
                    "end": max(s_dates)
                })

        # -----------------------------------------------------
        # STEP 4: TORIS Strikeout Sheet (Invalid/Dupe)
        # -----------------------------------------------------
        log(f"MARKING SHEET START → {file}")
        invalid_list, dupe_list = mark_sheet_with_strikeouts(path, rows, strike_color)

        # Save strikeout classification for Summary
        for inv in invalid_list:
            summary_data[full_key]["skipped_unknown"].append({
                "date": inv.get("date"),
                "raw": inv.get("raw"),
            })
        for d in dupe_list:
            summary_data[full_key]["skipped_dupe"].append({
                "date": d.get("date"),
                "ship": d.get("ship"),
            })

        # -----------------------------------------------------
        # STEP 5: Extract Valid Underway Periods (Ship-based)
        # -----------------------------------------------------
        # Group rows by ship and consolidate continuous days
        by_ship = {}
        for r in rows:
            if r.get("valid"):
                ship = r["ship"]
                if ship not in by_ship:
                    by_ship[ship] = []
                by_ship[ship].append(r["date"])

        # Collapse dates per ship into valid PG13 periods
        for ship, date_list in by_ship.items():
            sorted_dates = sorted(date_list)
            start = sorted_dates[0]
            prev = start
            for i in range(1, len(sorted_dates)):
                curr = sorted_dates[i]
                delta = (curr - prev).days
                if delta > 1:
                    # close old period
                    summary_data[full_key]["periods"].append({
                        "ship": ship,
                        "start": start,
                        "end": prev
                    })
                    # new period
                    start = curr
                prev = curr

            # close final range
            summary_data[full_key]["periods"].append({
                "ship": ship,
                "start": start,
                "end": prev
            })

        # -----------------------------------------------------
        # STEP 6: Generate PG13 PDFs for each valid period
        # -----------------------------------------------------
        for p in summary_data[full_key]["periods"]:
            make_pdf_for_ship(
                ship=p["ship"],
                periods=[p],
                name=full_key
            )

    # ---------------------------------------------------------
    # STEP 7: Generate Summary Files (TXT + PDF)
    # ---------------------------------------------------------
    write_summary_files(summary_data)

    # ---------------------------------------------------------
    # STEP 8: Merge All PDFs into PACKAGE
    # (Fixed order: merge happens AFTER summary files exist)
    # ---------------------------------------------------------
    merge_all_pdfs()

    # ---------------------------------------------------------
    # DONE
    # ---------------------------------------------------------
    log("PROCESS COMPLETE")
