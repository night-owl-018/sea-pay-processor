import os
from datetime import datetime, date, timedelta

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from app.core.logger import log
from app.core.config import SUMMARY_TXT_FOLDER, SUMMARY_PDF_FOLDER, TRACKER_FOLDER


# ------------------------------------------------
# DATE HELPERS
# ------------------------------------------------

def _fmt_mdY(d):
    """
    Return M/D/YYYY (no leading zeros) or 'UNKNOWN'.
    """
    if not d:
        return "UNKNOWN"
    if isinstance(d, datetime) or isinstance(d, date):
        return f"{d.month}/{d.day}/{d.year}"
    # If it's already a string, just return it
    return str(d)


def _parse_any_date(val):
    """
    Try to normalize anything that looks like a date to a datetime.
    Safe: returns None if it cannot parse.
    """
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime(val.year, val.month, val.day)
    if isinstance(val, str):
        s = val.strip()
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    return None


# ------------------------------------------------
# SUMMARY WRITER
# ------------------------------------------------

def write_summary_files(summary_data):
    """
    Writes per-member TXT + PDF summaries and a global SEA_PAY_TRACKER.txt.

    Supports two paths:
      • If info already has 'valid_periods', 'invalid_events', 'events_followed',
        'tracker_lines' → uses those EXACTLY (Option C).
      • Otherwise builds them from 'periods', 'skipped_dupe', 'skipped_unknown'
        (Option 1 fallback).
    """

    os.makedirs(SUMMARY_TXT_FOLDER, exist_ok=True)
    os.makedirs(SUMMARY_PDF_FOLDER, exist_ok=True)
    os.makedirs(TRACKER_FOLDER, exist_ok=True)

    tracker_agg_lines = []

    for member_key, info in summary_data.items():
        last = (info.get("last") or "UNKNOWN").strip()
        first = (info.get("first") or "").strip()
        rate = (info.get("rate") or "UNKNOWN").strip()

        # ----------------------------------------
        # 1. Try to use precomputed lists (Option C)
        # ----------------------------------------
        valid_periods = info.get("valid_periods") or []
        invalid_events = info.get("invalid_events") or []
        events_followed = info.get("events_followed") or []
        tracker_lines = info.get("tracker_lines") or []

        # ----------------------------------------
        # 2. Fallback: build from raw periods (Option 1)
        # ----------------------------------------
        raw_periods = info.get("periods") or []
        skipped_dupe = info.get("skipped_dupe") or []
        skipped_unknown = info.get("skipped_unknown") or []

        # a) VALID PERIODS (grouped by ship, continuous ranges)
        if not valid_periods and raw_periods:
            ship_map = {}
            for p in raw_periods:
                ship = (p.get("ship") or "UNKNOWN").strip()
                start = p.get("start")
                end = p.get("end")
                start_dt = _parse_any_date(start)
                end_dt = _parse_any_date(end)
                if not start_dt or not end_dt:
                    continue
                ship_map.setdefault(ship, []).append((start_dt, end_dt))

            merged = []
            for ship, ranges in ship_map.items():
                ranges.sort(key=lambda r: r[0])  # sort by start
                cur_start, cur_end = ranges[0]
                for s, e in ranges[1:]:
                    if s <= cur_end + timedelta(days=1):
                        # continuous (or overlapping) with current block
                        if e > cur_end:
                            cur_end = e
                    else:
                        merged.append((ship, cur_start, cur_end))
                        cur_start, cur_end = s, e
                merged.append((ship, cur_start, cur_end))
            valid_periods = merged

        # b) INVALID EVENTS from skipped_dupe / skipped_unknown
        if not invalid_events and (skipped_dupe or skipped_unknown):
            tmp_invalid = []

            for d in skipped_dupe:
                d_dt = _parse_any_date(d.get("date"))
                ship = (d.get("ship") or d.get("ship_name") or "UNKNOWN").strip()
                reason = "Duplicate entry for date"
                tmp_invalid.append((ship, d_dt, reason))

            for u in skipped_unknown:
                d_dt = _parse_any_date(u.get("date"))
                ship = (u.get("ship") or u.get("ship_name") or "UNKNOWN").strip()
                reason = u.get("reason") or "Invalid / non-payable event"
                tmp_invalid.append((ship, d_dt, reason))

            invalid_events = tmp_invalid

        # c) EVENTS FOLLOWED if not present
        if not events_followed:
            tmp_events = []

            # Valid ranges first (chronological)
            for ship, start_dt, end_dt in sorted(
                valid_periods,
                key=lambda r: (_parse_any_date(r[1]) or datetime.max)
            ):
                tmp_events.append(
                    f"{_fmt_mdY(start_dt)} TO {_fmt_mdY(end_dt)} | {ship} | PAY AUTHORIZED"
                )

            # Then invalid events
            for ship, d_dt, reason in sorted(
                invalid_events,
                key=lambda r: (_parse_any_date(r[1]) or datetime.max)
            ):
                tmp_events.append(
                    f"{_fmt_mdY(d_dt)} | {ship} | {reason}"
                )

            events_followed = tmp_events

        # d) TRACKER LINES if not precomputed
        if not tracker_lines:
            t_lines = []

            for ship, start_dt, end_dt in valid_periods:
                t_lines.append(
                    f"{rate} {last}, {first} | {ship} | "
                    f"{_fmt_mdY(start_dt)} TO {_fmt_mdY(end_dt)} | VALID"
                )

            for ship, d_dt, reason in invalid_events:
                t_lines.append(
                    f"{rate} {last}, {first} | {ship} | "
                    f"{_fmt_mdY(d_dt)} | {reason}"
                )

            tracker_lines = t_lines

        # Add to global tracker
        tracker_agg_lines.extend(tracker_lines)

        # ----------------------------------------
        # 3. BUILD SUMMARY TEXT
        # ----------------------------------------
        header = []
        header.append(f"{rate} {last}".upper())
        header.append("")
        header.append("VALID SEA PAY PERIODS (PAY AUTHORIZED):")
        header.append("")

        if valid_periods:
            for ship, start_dt, end_dt in valid_periods:
                header.append(
                    f"- {ship} | {_fmt_mdY(start_dt)} TO {_fmt_mdY(end_dt)}"
                )
        else:
            header.append("- NONE")

        header.append("")
        header.append("INVALID / NON-PAYABLE ENTRIES:")
        header.append("")

        if invalid_events:
            for ship, d_dt, reason in invalid_events:
                header.append(
                    f"- {ship} | {_fmt_mdY(d_dt)} | {reason}"
                )
        else:
            header.append("- NONE")

        header.append("")
        header.append("EVENTS FOLLOWED:")
        header.append("")

        if events_followed:
            for e in events_followed:
                header.append(f"- {e}")
        else:
            header.append("- NONE")

        header.append("")

        # ----------------------------------------
        # 4. WRITE SUMMARY TXT
        # ----------------------------------------
        filename_base = f"{rate}_{last}_{first}".strip().replace(" ", "_")
        txt_path = os.path.join(SUMMARY_TXT_FOLDER, f"{filename_base}_SUMMARY.txt")

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(header))

        log(f"SUMMARY WRITTEN → {txt_path}")

        # ----------------------------------------
        # 5. WRITE SUMMARY PDF (simple 1+ page text)
        # ----------------------------------------
        pdf_path = os.path.join(SUMMARY_PDF_FOLDER, f"{filename_base}_SUMMARY.pdf")
        c = canvas.Canvas(pdf_path, pagesize=letter)
        x, y = 40, 770
        line_height = 12

        for line in header:
            if y < 40:  # new page if near bottom
                c.showPage()
                c.setFont("Helvetica", 10)
                x, y = 40, 770
            c.setFont("Helvetica", 10)
            c.drawString(x, y, line)
            y -= line_height

        c.save()
        log(f"SUMMARY PDF WRITTEN → {pdf_path}")

    # ----------------------------------------
    # 6. GLOBAL TRACKER FILE
    # ----------------------------------------
    if tracker_agg_lines:
        tracker_path = os.path.join(TRACKER_FOLDER, "SEA_PAY_TRACKER.txt")
        with open(tracker_path, "w", encoding="utf-8") as f:
            f.write("RATE LAST, FIRST | SHIP | PERIOD / DATE | STATUS\n\n")
            for line in tracker_agg_lines:
                f.write(line + "\n")
        log(f"TRACKER WRITTEN → {tracker_path}")
    else:
        log("TRACKER EMPTY → no tracker lines generated")
