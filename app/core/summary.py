import os
from datetime import datetime

from app.core.logger import log
from app.core.config import SUMMARY_TXT_FOLDER


def fmt(d):
    """Format date as MM-DD-YYYY or 'UNKNOWN'."""
    if not d:
        return "UNKNOWN"
    return datetime.strftime(d, "%m-%d-%Y")


def write_summary_files(summary_data):
    """
    Writes PSD-style text summaries, now with:
    - EVENTS FOLLOWED (chronological log)
    """

    for member_key, info in summary_data.items():

        rate = info.get("rate", "UNK")
        last = info.get("last", "UNK")
        first = info.get("first", "")

        reporting_periods = info.get("reporting_periods", [])
        valid_periods = info.get("periods", [])
        invalid_unknown = info.get("skipped_unknown", [])
        invalid_dupe = info.get("skipped_dupe", [])

        # Determine documented period
        if reporting_periods:
            min_s = min(r["start"] for r in reporting_periods if r["start"])
            max_e = max(r["end"] for r in reporting_periods if r["end"])
        else:
            min_s, max_e = None, None

        out = []

        # ------------------------------------------------------------
        # HEADER
        # ------------------------------------------------------------
        out.append("PSD SEA PAY SUMMARY\n")
        out.append(f"Member: {rate} {last}\n")
        out.append(f"Documented Period: {fmt(min_s)} to {fmt(max_e)}\n")

        # ------------------------------------------------------------
        # VALID SEA PAY PERIODS
        # ------------------------------------------------------------
        out.append("\nVALID SEA PAY PERIODS (PAY AUTHORIZED):")

        total_valid_days = 0

        for p in valid_periods:
            ship = p["ship"]
            s = p["start"]
            e = p["end"]
            days = (e - s).days + 1
            total_valid_days += days

            suffix = "s" if days != 1 else ""
            out.append(
                f"\n- {ship} | {fmt(s)} TO {fmt(e)} | {days} Day{suffix}"
            )

        out.append(f"\n\nTotal Valid Days: {total_valid_days}\n")

        # ------------------------------------------------------------
        # INVALID ENTRIES (existing section)
        # ------------------------------------------------------------
        out.append("\nINVALID / NON-PAYABLE ENTRIES:")

        invalid_items = []

        # Unknown / suppressed rows
        for u in invalid_unknown:
            invalid_items.append((
                u.get("date", ""),
                u.get("ship", "UNK"),
                u.get("reason", "Invalid event")
            ))

        # Duplicate rows
        for d in invalid_dupe:
            invalid_items.append((
                d.get("date", ""),
                d.get("ship", "UNK"),
                d.get("reason", "Duplicate entry for date")
            ))

        # Sort by date, then ship (Q1 A)
        invalid_items.sort(key=lambda x: (x[0], x[1]))

        invalid_days_set = set()

        for date, ship, reason in invalid_items:
            out.append(f"\n- {ship} | {date} | {reason}")
            invalid_days_set.add(date)

        out.append(f"\n\nTotal Invalid Days: {len(invalid_days_set)}\n")

        # ============================================================
        # PATCH A — EVENTS FOLLOWED (NEW SECTION)
        # Appears directly after INVALID ENTRIES (Q2 A)
        # ============================================================
        out.append("\nEVENTS FOLLOWED (CHRONOLOGICAL LOG):")

        # Build chronological list:
        event_log = []

        # Add valid events
        for p in valid_periods:
            # Expand each period into raw dates
            s = p["start"]
            e = p["end"]
            delta = (e - s).days
            for i in range(delta + 1):
                d = s + timedelta(days=i)
                event_log.append((
                    d.strftime("%m/%d/%Y"),
                    p["ship"],
                    "Pay Authorized"  # Q3 C
                ))

        # Add invalid events
        for date, ship, reason in invalid_items:
            event_log.append((date, ship, reason))

        # Sort chronologically (Q1 A)
        def _datekey(row):
            try:
                return datetime.strptime(row[0], "%m/%d/%Y")
            except Exception:
                return datetime.min

        event_log.sort(key=_datekey)

        # Output log
        for date, ship, reason in event_log:
            out.append(f"\n{date} | {ship} | {reason}")

        out.append("\n")

        # ------------------------------------------------------------
        # DOCUMENTS PROVIDED
        # ------------------------------------------------------------
        out.append("\nDOCUMENTS PROVIDED:")
        out.append("\n- Generated Sea Pay PG13")
        out.append("\n- TORIS Sea Pay Cert Sheet")
        out.append("\n- Summary PDF\n")

        # ------------------------------------------------------------
        # NOTES
        # ------------------------------------------------------------
        notes = []

        if len(valid_periods) > 1:
            notes.append("Valid events confirmed using continuous-date logic.")

        if len(invalid_days_set) > 0:
            notes.append("SBTT/MITE and invalid events suppressed per policy.")
            notes.append("TORIS sheet corrected and annotated.")

        if notes:
            out.append("\nNOTES FOR PSD:")
            for n in notes:
                out.append(f"\n- {n}")
            out.append("\n")

        out.append("\nGenerated by STG1 NIVERA – ATGSD SEA PAY PROCESSOR\n")

        # ------------------------------------------------------------
        # SAVE SUMMARY FILE
        # ------------------------------------------------------------
        filename = f"{rate}_{last}_{first}_SUMMARY.txt".replace(" ", "_")
        summary_path = os.path.join(SUMMARY_TXT_FOLDER, filename)

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("".join(out))

        log(f"SUMMARY WRITTEN → {summary_path}")
