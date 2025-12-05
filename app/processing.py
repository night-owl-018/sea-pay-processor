import os
import re
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
# TEXT TO PDF WRITER
# ------------------------------------------------

def _write_pdf_from_lines(lines, pdf_path):
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter

    text = c.beginText(40, height - 40)
    text.setFont("Courier", 9)
    max_chars = 95

    if not lines:
        lines = ["No validation data available."]

    for raw in lines:
        clean = raw.encode("ascii", "ignore").decode()

        while len(clean) > max_chars:
            text.textLine(clean[:max_chars])
            clean = clean[max_chars:]

            if text.getY() < 40:
                c.drawText(text)
                c.showPage()
                text = c.beginText(40, height - 40)
                text.setFont("Courier", 9)

        text.textLine(clean)

        if text.getY() < 40:
            c.drawText(text)
            c.showPage()
            text = c.beginText(40, height - 40)
            text.setFont("Courier", 9)

    c.drawText(text)
    c.save()


# ------------------------------------------------
# DATE FORMATTING HELPERS
# ------------------------------------------------

def _fmt_dmy(d, default="UNKNOWN"):
    if not d or not hasattr(d, "strftime"):
        return default
    return d.strftime("%d %b %Y").upper()


def _fmt_iso(d, default=""):
    if not d or not hasattr(d, "strftime"):
        return default
    return d.strftime("%Y-%m-%d")


def _parse_flex_date(date_str):
    """
    Parse date in any of these formats:
      8/4/2025
      8-4-2025
      8_4_2025
    Normalized to %m/%d/%Y internally.
    """
    if not date_str:
        return None

    cleaned = re.sub(r"[-_]", "/", date_str.strip())

    try:
        return datetime.strptime(cleaned, "%m/%d/%Y")
    except Exception:
        return None


# ------------------------------------------------
# BULLETPROOF REPORTING PERIOD EXTRACTOR
# ------------------------------------------------

def extract_reporting_period(raw_text, filename):
    """
    Extract the reporting window from either:
      • The text inside the Sea Duty Certification Sheet (preferred)
      • The filename (fallback)
    """
    # 1) BEST SOURCE → The sheet text itself:
    # Matches actual TORIS output:
    #   "From: 8/4/2025 To: 11/24/2025"
    m1 = re.search(
        r"From:\s*(\d{1,2}/\d{1,2}/\d{4})\s*To:\s*(\d{1,2}/\d{1,2}/\d{4})",
        raw_text,
        re.IGNORECASE,
    )
    if m1:
        start_str, end_str = m1.group(1), m1.group(2)
        start_dt = datetime.strptime(start_str, "%m/%d/%Y")
        end_dt = datetime.strptime(end_str, "%m/%d/%Y")
        return start_dt, end_dt, f"{start_str} to {end_str}"

    # 2) FALLBACK → Filename flexible matcher:
    # Handles:
    #   8_4_2025 - 11_24_2025.pdf
    #   8-4-2025 to 11-24-2025.pdf
    #   8/4/2025 - 11/24/2025.pdf
    m2 = re.search(
        r"(\d{1,2}[-_/]\d{1,2}[-_/]\d{4})\s*(?:to|-)\s*(\d{1,2}[-_/]\d{1,2}[-_/]\d{4})",
        filename,
        re.IGNORECASE,
    )

    if m2:
        raw_start, raw_end = m2.group(1), m2.group(2)
        start_dt = _parse_flex_date(raw_start)
        end_dt = _parse_flex_date(raw_end)

        start_str = re.sub(r"[-_]", "/", raw_start)
        end_str = re.sub(r"[-_]", "/", raw_end)

        if start_dt and end_dt:
            return start_dt, end_dt, f"{start_str} to {end_str}"

    # 3) FAILSAFE:
    return None, None, "UNKNOWN"


# ------------------------------------------------
# VALIDATION REPORTS (PER SAILOR + MASTER)
# ------------------------------------------------

def write_validation_reports(summary_data):
    validation_dir = os.path.join(OUTPUT_DIR, "validation")
    os.makedirs(validation_dir, exist_ok=True)

    master_txt = os.path.join(validation_dir, "VALIDATION_REPORTS_MASTER.txt")
    master_pdf = os.path.join(validation_dir, "VALIDATION_REPORTS_MASTER.pdf")

    master_lines = []

    if not summary_data:
        with open(master_txt, "w", encoding="utf-8") as f:
            f.write("No validation data.")
        _write_pdf_from_lines(["No validation data."], master_pdf)
        return

    def sort_key(item):
        _k, sd = item
        return (
            (sd.get("last") or "").upper(),
            (sd.get("first") or "").upper()
        )

    for key, sd in sorted(summary_data.items(), key=sort_key):
        rate = sd.get("rate", "")
        last = sd.get("last", "")
        first = sd.get("first", "")

        display_name = f"{rate} {last}, {first}".strip()

        periods = sd.get("periods", [])
        skipped_unknown = sd.get("skipped_unknown", [])
        skipped_dupe = sd.get("skipped_dupe", [])
        reporting_periods = sd.get("reporting_periods", [])

        total_days = sum(p["days"] for p in periods)

        lines = []
        lines.append("=" * 80)
        lines.append(f"SAILOR: {display_name}")
        lines.append("=" * 80)
        lines.append("")

        # REPORTING WINDOWS
        lines.append("REPORTING PERIODS")
        lines.append("-" * 80)
        if reporting_periods:
            lines.append("  REPORTING PERIOD START     REPORTING PERIOD END       SOURCE FILE")
            lines.append("  -------------------------  -------------------------  ----------------------------")
            for rp in reporting_periods:
                rs = _fmt_dmy(rp.get("start"))
                re_ = _fmt_dmy(rp.get("end"))
                src = rp.get("file", "")
                lines.append(f"  {rs:25}  {re_:25}  {src}")
        else:
            lines.append("  NONE")
        lines.append("")

        # SUMMARY
        lines.append("SUMMARY")
        lines.append("-" * 80)
        lines.append(f"  Total Valid Sea Pay Days : {total_days}")
        lines.append(f"  Valid Period Count       : {len(periods)}")
        lines.append(f"  Invalid Events           : {len(skipped_unknown)}")
        lines.append(f"  Duplicate Date Conflicts : {len(skipped_dupe)}")
        lines.append("")

        # VALID PERIODS
        lines.append("VALID SEA PAY PERIODS")
        lines.append("-" * 80)
        if periods:
            lines.append("  SHIP                 START            END              DAYS")
            lines.append("  -------------------  ----------------  ----------------  ----")
            for p in periods:
                ship = (p["ship"] or "").upper()
                start = _fmt_dmy(p["start"])
                end = _fmt_dmy(p["end"])
                days = p["days"]
                lines.append(f"  {ship[:19]:19}  {start:16}  {end:16}  {days:4}")
        else:
            lines.append("  NONE")
        lines.append("")

        # INVALID EVENTS
        lines.append("INVALID / EXCLUDED EVENTS")
        lines.append("-" * 80)
        if skipped_unknown:
            for entry in skipped_unknown:
                dt = entry.get("date", "UNKNOWN")
                ship = entry.get("ship") or entry.get("ship_name", "")
                reason = entry.get("reason", "Excluded")
                detail = dt
                if ship:
                    detail += f" | {ship}"
                lines.append(f"  - {detail} — {reason}")
        else:
            lines.append("  NONE")
        lines.append("")

        # DUPLICATES
        lines.append("DUPLICATES")
        lines.append("-" * 80)
        if skipped_dupe:
            for entry in skipped_dupe:
                dt = entry.get("date", "UNKNOWN")
                ship = entry.get("ship") or entry.get("ship_name", "")
                occ = entry.get("occ_idx") or entry.get("occurrence", "")
                detail = dt
                if ship:
                    detail += f" | {ship}"
                if occ:
                    detail += f" | occurrence #{occ}"
                lines.append(f"  - {detail}")
        else:
            lines.append("  NONE")
        lines.append("")

        # OUTPUT PER-SAILOR REPORT
        safe_name = f"{rate}_{last}_{first}".replace(" ", "_").replace(",", "")
        txt_path = os.path.join(validation_dir, f"VALIDATION_{safe_name}.txt")
        pdf_path = os.path.join(validation_dir, f"VALIDATION_{safe_name}.pdf")

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        _write_pdf_from_lines(lines, pdf_path)

        master_lines.extend(lines)
        master_lines.append("=" * 80)
        master_lines.append("")

    with open(master_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(master_lines))

    _write_pdf_from_lines(master_lines, master_pdf)


# ------------------------------------------------
# VALIDATION LEDGER (MASTER VIEW)
# ------------------------------------------------

def write_validation_ledger(summary_data, generated_at):
    """
    Produces a perfectly aligned ASCII box-table ledger with overflow protection.
    Total line width = 90 characters. Guaranteed no wrapping.
    """

    validation_dir = os.path.join(OUTPUT_DIR, "validation")
    os.makedirs(validation_dir, exist_ok=True)

    txt_path = os.path.join(validation_dir, "VALIDATION_LEDGER.txt")
    pdf_path = os.path.join(validation_dir, "VALIDATION_LEDGER.pdf")

    # Column exact width limits (characters)
    W_RATE = 4
    W_NAME = 24
    W_START = 17
    W_END = 17
    W_GEN = 20

    # Build header border
    border = (
        "+" + "-" * (W_RATE + 2)
        + "+" + "-" * (W_NAME + 2)
        + "+" + "-" * (W_START + 2)
        + "+" + "-" * (W_END + 2)
        + "+" + "-" * (W_GEN + 2)
        + "+"
    )

    lines = []
    lines.append(border)
    lines.append(
        "| RATE | NAME" + " " * (W_NAME - 4) +
        " | START DATE" + " " * (W_START - 10) +
        " | END DATE" + " " * (W_END - 8) +
        " | GENERATED" + " " * (W_GEN - 9) + " |"
    )
    lines.append(border)

    def fix_width(text, width):
        """Trim or pad text to fixed width, add ellipsis if needed."""
        if text is None:
            text = ""
        text = str(text)
        if len(text) > width:
            return text[: width - 1] + "…"  # ellipsis
        return text.ljust(width)

    def sort_key(item):
        _k, sd = item
        return ((sd.get("last") or "").upper(), (sd.get("first") or "").upper())

    gen_str = generated_at.strftime("%d %b %Y %H:%M")

    for key, sd in sorted(summary_data.items(), key=sort_key):
        rate = sd.get("rate", "") or ""
        last = sd.get("last", "") or ""
        first = sd.get("first", "") or ""
        name = f"{last}, {first}"

        reporting_periods = sd.get("reporting_periods", [])
        if not reporting_periods:
            # Still output one row with UNKNOWNs
            start_s = "UNKNOWN"
            end_s = "UNKNOWN"

            row = (
                "| " + fix_width(rate, W_RATE) + " | " +
                fix_width(name, W_NAME) + " | " +
                fix_width(start_s, W_START) + " | " +
                fix_width(end_s, W_END) + " | " +
                fix_width(gen_str, W_GEN) + " |"
            )

            # Overflow protection: hard-trim final line
            if len(row) > 90:
                row = row[:90]

            lines.append(row)
            continue

        # Multiple reporting windows possible
        for rp in reporting_periods:
            rs = _fmt_dmy(rp.get("start"))
            re_ = _fmt_dmy(rp.get("end"))

            row = (
                "| " + fix_width(rate, W_RATE) + " | " +
                fix_width(name, W_NAME) + " | " +
                fix_width(rs, W_START) + " | " +
                fix_width(re_, W_END) + " | " +
                fix_width(gen_str, W_GEN) + " |"
            )

            if len(row) > 90:
                row = row[:90]

            lines.append(row)

    lines.append(border)

    # Write TXT
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # Write matching PDF
    _write_pdf_from_lines(lines, pdf_path)



# ------------------------------------------------
# TRACKING (JSON + CSV)
# ------------------------------------------------

def write_json_tracker(summary_data, generated_at):
    import json

    tracking_dir = os.path.join(OUTPUT_DIR, "tracking")
    os.makedirs(tracking_dir, exist_ok=True)

    payload = {
        "generated_at": generated_at.isoformat(),
        "tool_version": "1.1.0",
        "sailors": []
    }

    for key, sd in summary_data.items():
        periods = sd.get("periods", [])
        reporting_periods = sd.get("reporting_periods", [])
        skipped_unknown = sd.get("skipped_unknown", [])
        skipped_dupe = sd.get("skipped_dupe", [])

        total_days = sum(p["days"] for p in periods)
        status = "VALID" if not (skipped_unknown or skipped_dupe) else "WITH_DISCREPANCIES"

        payload["sailors"].append({
            "rate": sd.get("rate", ""),
            "last": sd.get("last", ""),
            "first": sd.get("first", ""),
            "total_days": total_days,
            "status": status,
            "reporting_periods": [
                {
                    "start": _fmt_iso(rp.get("start")),
                    "end": _fmt_iso(rp.get("end")),
                    "file": rp.get("file", ""),
                    "range_text": rp.get("range_text", "")
                }
                for rp in reporting_periods
            ],
            "periods": [
                {
                    "ship": p["ship"],
                    "start": _fmt_iso(p["start"]),
                    "end": _fmt_iso(p["end"]),
                    "days": p["days"],
                    "reporting_period_start": _fmt_iso(p.get("sheet_start")),
                    "reporting_period_end": _fmt_iso(p.get("sheet_end")),
                    "source_file": p.get("sheet_file", "")
                }
                for p in periods
            ],
            "invalid_events": skipped_unknown,
            "duplicate_events": skipped_dupe
        })

    out_path = os.path.join(tracking_dir, f"SeaPay_Tracking_{generated_at.strftime('%Y-%m-%d')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def write_csv_tracker(summary_data, generated_at):
    import csv

    tracking_dir = os.path.join(OUTPUT_DIR, "tracking")
    os.makedirs(tracking_dir, exist_ok=True)

    csv_path = os.path.join(tracking_dir, f"SeaPay_Tracking_{generated_at.strftime('%Y-%m-%d')}.csv")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Rate",
            "Last",
            "First",
            "ReportingPeriodStart",
            "ReportingPeriodEnd",
            "Ship",
            "Start",
            "End",
            "Days",
            "InvalidCount",
            "DuplicateCount",
            "Status",
            "GeneratedAt",
            "SourceFile"
        ])

        generated_at_str = generated_at.isoformat()

        for key, sd in summary_data.items():
            periods = sd.get("periods", [])
            reporting_periods = sd.get("reporting_periods", [])
            skipped_unknown = sd.get("skipped_unknown", [])
            skipped_dupe = sd.get("skipped_dupe", [])

            invalid_count = len(skipped_unknown)
            dupe_count = len(skipped_dupe)
            status = "VALID" if not (invalid_count or dupe_count) else "WITH_DISCREPANCIES"

            rate = sd.get("rate", "")
            last = sd.get("last", "")
            first = sd.get("first", "")

            if reporting_periods:
                rp_start = _fmt_iso(reporting_periods[0]["start"])
                rp_end = _fmt_iso(reporting_periods[0]["end"])
            else:
                rp_start = ""
                rp_end = ""

            if periods:
                for p in periods:
                    writer.writerow([
                        rate,
                        last,
                        first,
                        rp_start,
                        rp_end,
                        p["ship"],
                        _fmt_iso(p["start"]),
                        _fmt_iso(p["end"]),
                        p["days"],
                        invalid_count,
                        dupe_count,
                        status,
                        generated_at_str,
                        p.get("sheet_file", "")
                    ])
            else:
                writer.writerow([
                    rate,
                    last,
                    first,
                    rp_start,
                    rp_end,
                    "",
                    "",
                    "",
                    0,
                    invalid_count,
                    dupe_count,
                    status,
                    generated_at_str,
                    ""
                ])


# ------------------------------------------------
# MAIN PROCESSOR
# ------------------------------------------------

def process_all(strike_color="black"):
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

        # Extract reporting period
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

        # Group periods by ship
        groups = group_by_ship(rows)

        total_days = sum((g["end"] - g["start"]).days + 1 for g in groups)

        # Strikeout sheet
        marked_dir = os.path.join(OUTPUT_DIR, "marked_sheets")
        os.makedirs(marked_dir, exist_ok=True)
        marked_path = os.path.join(marked_dir, f"MARKED_{os.path.splitext(file)[0]}.pdf")

        mark_sheet_with_strikeouts(
            path,
            skipped_dupe,
            skipped_unknown,
            marked_path,
            total_days,
            strike_color=strike_color
        )

        # NAVPERS per ship
        ship_periods = {}
        for g in groups:
            ship_periods.setdefault(g["ship"], []).append(g)

        for ship, periods in ship_periods.items():
            make_pdf_for_ship(ship, periods, name)

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
                "reporting_periods": []
            }

        sd = summary_data[key]

        sd["reporting_periods"].append({
            "start": sheet_start,
            "end": sheet_end,
            "file": file,
            "range_text": sheet_range_text
        })

        for g in groups:
            days = (g["end"] - g["start"]).days + 1
            sd["periods"].append({
                "ship": g["ship"],
                "start": g["start"],
                "end": g["end"],
                "days": days,
                "sheet_start": sheet_start,
                "sheet_end": sheet_end,
                "sheet_file": file
            })

        sd["skipped_unknown"].extend(skipped_unknown)
        sd["skipped_dupe"].extend(skipped_dupe)

    # Merge 1070s
    merge_all_pdfs()

    # Summary
    write_summary_files(summary_data)

    # Validation
    write_validation_reports(summary_data)
    log("VALIDATION REPORTS DONE")

    write_validation_ledger(summary_data, run_generated_at)
    log("LEDGER DONE")

    # Tracking
    write_json_tracker(summary_data, run_generated_at)
    write_csv_tracker(summary_data, run_generated_at)
    log("TRACKING DONE")

    log("✅ ALL OPERATIONS COMPLETE")

