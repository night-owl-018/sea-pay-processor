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
# Helper: align date / event / time into fixed-width columns
# -------------------------------------------------------------------------
def align_rows_fixed_width(raw_text: str) -> str:
    """
    Rebuild schedule rows into a single logical line with fixed-width columns:
        DATE (12 chars) | EVENT (50 chars) | TIME (right-aligned, e.g. 0800–1600)

    This merges broken OCR fragments like:
        8/25/2025 CHOSIN (ASW
        T-2)
        þ 0800 1600

    Into:
        8/25/2025   CHOSIN (ASW T-2)                           0800–1600
    """
    lines = raw_text.splitlines()
    out_lines = []
    i = 0
    n = len(lines)

    date_pat = re.compile(r"^(?P<date>\d{1,2}/\d{1,2}/\d{4})(?P<rest>.*)$")
    time_pat = re.compile(r"^\s*þ?\s*(?P<t1>\d{3,4})\s+(?P<t2>\d{3,4})\s*$")

    while i < n:
        line = lines[i]
        stripped = line.strip()
        m_date = date_pat.match(stripped)

        if not m_date:
            # Non-schedule line: keep as-is
            out_lines.append(line)
            i += 1
            continue

        # We have a schedule row starting with a date
        date = m_date.group("date").strip()
        rest = m_date.group("rest").strip()
        event_parts = []
        if rest:
            event_parts.append(rest)

        # Consume continuation lines (event text)
        j = i + 1
        while j < n:
            nxt_raw = lines[j]
            nxt = nxt_raw.strip()

            # Stop if next line is another date
            if date_pat.match(nxt):
                break
            # Stop if it looks like a time line
            if time_pat.match(nxt):
                break
            # Stop on blank
            if not nxt:
                break

            # Otherwise treat as continuation of event text
            event_parts.append(nxt)
            j += 1

        # Now try to read a time line (if present)
        time_str = ""
        if j < n:
            m_time = time_pat.match(lines[j].strip())
            if m_time:
                t1 = m_time.group("t1").zfill(4)
                t2 = m_time.group("t2").zfill(4)
                time_str = f"{t1}\u2013{t2}"  # en dash
                j += 1

        # Build fixed-width line: 12 / 50 / time-right
        date_col = date.ljust(12)
        event_text = " ".join(event_parts).strip()
        event_col = event_text.ljust(50)[:50]
        time_col = time_str.rjust(11) if time_str else ""

        out_lines.append(f"{date_col}{event_col}{time_col}")

        i = j

    return "\n".join(out_lines)


# -------------------------------------------------------------------------
# Extract "Total Sea Pay Days for this reporting period: XX"
# -------------------------------------------------------------------------
def extract_total_days(text: str):
    """
    Extracts the numeric total from the standard line:
        'Total Sea Pay Days for this reporting period: 29'
    Returns int or None.
    """
    m = re.search(
        r"Total\s+Sea\s+Pay\s+Days\s+for\s+this\s+reporting\s+period:\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


# -------------------------------------------------------------------------
# Extract reporting period from TORIS header / filename
# -------------------------------------------------------------------------
def extract_reporting_period(text, filename=""):
    """
    Extracts the official sheet header date range:
    Example line in PDF:
        'From: 8/4/2025 To: 11/24/2025'
    """

    pattern = r"From:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*To:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})"
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        from_raw = match.group(1)
        to_raw = match.group(2)

        try:
            start = datetime.strptime(from_raw, "%m/%d/%Y")
            end = datetime.strptime(to_raw, "%m/%d/%Y")
        except Exception:
            return None, None, ""

        return start, end, f"{from_raw} - {to_raw}"

    # Fallback to filename like: "8_4_2025 - 11_24_2025"
    alt_pattern = r"(\d{1,2}_\d{1,2}_\d{4})\s*-\s*(\d{1,2}_\d{1,2}_\d{4})"
    m2 = re.search(alt_pattern, filename)

    if m2:
        try:
            s = datetime.strptime(m2.group(1).replace("_", "/"), "%m/%d/%Y")
            e = datetime.strptime(m2.group(2).replace("_", "/"), "%m/%d/%Y")
            return s, e, f"{m2.group(1)} - {m2.group(2)}"
        except Exception:
            return None, None, ""

    return None, None, ""


# -------------------------------------------------------------------------
# Clear PG13 output folder before each run
# -------------------------------------------------------------------------
def clear_pg13_folder():
    """Delete all existing PG13 PDFs before generating new ones."""
    try:
        if not os.path.isdir(SEA_PAY_PG13_FOLDER):
            os.makedirs(SEA_PAY_PG13_FOLDER, exist_ok=True)
        for f in os.listdir(SEA_PAY_PG13_FOLDER):
            fp = os.path.join(SEA_PAY_PG13_FOLDER, f)
            if os.path.isfile(fp):
                os.remove(fp)
    except Exception as e:
        log(f"PG13 CLEAR ERROR → {e}")


# -------------------------------------------------------------------------
# Main processing pipeline
# -------------------------------------------------------------------------
def process_all(strike_color="black"):
    """
    Main engine:
      * OCR each TORIS sheet
      * Align broken rows into fixed-width DATE / EVENT / TIME
      * Extract reporting period and Total Sea Pay Days
      * Parse rows, group by ship, compute valid days
      * Generate strikeout TORIS sheets
      * Generate NAVPERS 1070/613 PG13 PDFs
      * Write summary files, then merge PDFs
    """

    os.makedirs(SEA_PAY_PG13_FOLDER, exist_ok=True)
    os.makedirs(TORIS_CERT_FOLDER, exist_ok=True)

    clear_pg13_folder()

    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]
    if not files:
        log("NO INPUT FILES FOUND")
        return

    log("=== PROCESS STARTED ===")
    summary_data = {}

    for file in sorted(files):
        path = os.path.join(DATA_DIR, file)
        log(f"OCR → {file}")

        # 1. OCR + basic cleanup
        raw = strip_times(ocr_pdf(path))

        # 1a. Align schedule rows into fixed-width columns
        aligned = align_rows_fixed_width(raw)

        # 1b. Extract printed total from aligned text
        extracted_total_days = extract_total_days(aligned)

        # 2. Reporting period
        sheet_start, sheet_end, _ = extract_reporting_period(aligned, file)

        # 3. Extract name
        try:
            name = extract_member_name(aligned)
            log(f"NAME → {name}")
        except Exception as e:
            log(f"NAME ERROR → {e}")
            continue

        year = extract_year_from_filename(file)

        # 4. Parse rows into valid/dupes/unknown
        rows, skipped_dupe, skipped_unknown = parse_rows(aligned, year)

        # 5. Group valid rows by ship
        groups = group_by_ship(rows)

        # Compute valid total days
        computed_total_days = sum((g["end"] - g["start"]).days + 1 for g in groups)

        # 6. Resolve identity
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

        # Add reporting period
        sd["reporting_periods"].append({
            "start": sheet_start,
            "end": sheet_end,
            "file": file,
        })

        # Add valid periods
        for g in groups:
            sd["periods"].append({
                "ship": g["ship"],
                "start": g["start"],
                "end": g["end"],
                "days": (g["end"] - g["start"]).days + 1,
                "sheet_file": file,
            })

        # Add skipped rows
        sd["skipped_unknown"].extend(skipped_unknown)
        sd["skipped_dupe"].extend(skipped_dupe)

        # Build TORIS cert filename
        hf = sheet_start.strftime("%m-%d-%Y") if sheet_start else "UNKNOWN"
        ht = sheet_end.strftime("%m-%d-%Y") if sheet_end else "UNKNOWN"

        toris_filename = (
            f"{rate}_{last}_{first}"
            f"__TORIS_SEA_DUTY_CERT_SHEETS__{hf}_TO_{ht}.pdf"
        ).replace(" ", "_")

        toris_path = os.path.join(TORIS_CERT_FOLDER, toris_filename)

        # Create strikeout TORIS sheet with both printed and computed totals
        mark_sheet_with_strikeouts(
            path,
            skipped_dupe,
            skipped_unknown,
            toris_path,
            extracted_total_days,
            computed_total_days,
            strike_color=strike_color,
        )

        # Create NAVPERS 1070/613 PG13 PDFs (1 sheet per ship/period)
        ship_map = {}
        for g in groups:
            ship_map.setdefault(g["ship"], []).append(g)

        for ship, ship_periods in ship_map.items():
            make_pdf_for_ship(ship, ship_periods, name)

    # Write summary files (TXT + any others)
    write_summary_files(summary_data)

    # Merge into final packages (PG13 / TORIS / SUMMARY)
    merge_all_pdfs()

    log("PROCESS COMPLETE")
