import re
from datetime import datetime, timedelta

from app.core.ships import match_ship


def extract_year_from_filename(fn):
    """Extract 4-digit year from filename or fallback to current year."""
    m = re.search(r"(20\d{2})", fn)
    return m.group(1) if m else str(datetime.now().year)


def parse_rows(text, year):
    """
    Smart TORIS parser.
    PATCHES ADDED:
    - Added 'reason' fields for all invalid events
    - Added 'ship' field where appropriate
    - No change to mission / duplicate logic
    """

    rows = []
    skipped_duplicates = []
    skipped_unknown = []

    lines = text.splitlines()

    per_date_entries = {}
    date_order = []

    # PASS 1 — Collect entries by date
    for i, line in enumerate(lines):
        m = re.match(r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", line)
        if not m:
            continue

        mm, dd, yy = m.groups()
        y = ("20" + yy) if yy and len(yy) == 2 else yy or year
        date = f"{mm.zfill(2)}/{dd.zfill(2)}/{y}"

        raw = line[m.end():]
        if i + 1 < len(lines):
            raw += " " + lines[i + 1]

        cleaned = raw.strip()
        upper = cleaned.upper()

        entry = {
            "raw": cleaned,
            "upper": upper,
            "line_index": i,
            "date": date,
            "ship": None,
            "kind": None,
            "occ_idx": None,
        }

        if date not in per_date_entries:
            per_date_entries[date] = []
            date_order.append(date)

        per_date_entries[date].append(entry)

    # Helper for mission preference
    def is_mission(e):
        up = e["upper"]
        return any(tag in up for tag in ("M-1", "M1", "M-2", "M2"))

    # PASS 2 — Classify and select a single valid row per date
    for date in date_order:
        entries = per_date_entries[date]

        occ = 0
        for e in entries:
            occ += 1
            e["occ_idx"] = occ

            up = e["upper"]

            # SBTT event
            if "SBTT" in up:
                e["kind"] = "sbtt"
                skipped_unknown.append({
                    "date": date,
                    "raw": "SBTT",
                    "occ_idx": occ,
                    "reason": "SBTT In-Port Event",
                    "ship": None,
                })
                continue

            ship = match_ship(e["raw"])
            e["ship"] = ship

            # Unknown or non-platform
            if not ship:
                e["kind"] = "unknown"
                skipped_unknown.append({
                    "date": date,
                    "raw": e["raw"],
                    "occ_idx": occ,
                    "reason": "Unknown or Non-Platform Event",
                    "ship": None,
                })
            else:
                e["kind"] = "valid"

        # Filter valid
        valids = [e for e in entries if e["kind"] == "valid"]

        if not valids:
            continue

        ships_set = set(e["ship"] for e in valids)

        # Only one ship → keep first valid
        if len(ships_set) == 1:
            kept = valids[0]
        else:
            mission_valids = [e for e in valids if is_mission(e)]
            if mission_valids:
                kept = sorted(mission_valids, key=lambda e: e["occ_idx"])[0]
            else:
                kept = sorted(valids, key=lambda e: e["occ_idx"])[0]

        # Store valid row
        rows.append({
            "date": date,
            "ship": kept["ship"],
            "occ_idx": kept["occ_idx"],
        })

        # Duplicates
        for e in valids:
            if e is kept:
                continue
            skipped_duplicates.append({
                "date": date,
                "ship": e["ship"],
                "occ_idx": e["occ_idx"],
                "reason": "Duplicate entry for date",
            })

    return rows, skipped_duplicates, skipped_unknown


def group_by_ship(rows):
    """Group continuous dates for each ship into start-end periods."""
    grouped = {}

    for r in rows:
        dt = datetime.strptime(r["date"], "%m/%d/%Y")
        grouped.setdefault(r["ship"], []).append(dt)

    output = []

    for ship, dates in grouped.items():
        dates = sorted(set(dates))
        start = prev = dates[0]

        for d in dates[1:]:
            if d == prev + timedelta(days=1):
                prev = d
            else:
                output.append({"ship": ship, "start": start, "end": prev})
                start = prev = d

        output.append({"ship": ship, "start": start, "end": prev})

    return output
