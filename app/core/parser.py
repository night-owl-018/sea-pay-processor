import re
from datetime import datetime, timedelta

from app.core.ships import match_ship


def extract_year_from_filename(fn):
    """Extract 4-digit year from filename or fallback to current year."""
    m = re.search(r"(20\d{2})", fn)
    return m.group(1) if m else str(datetime.now().year)


# ----------------------------------------------------------
# DETECT TRAINING EVENT TYPE (CLEAN VARIANT LABELS)
# ----------------------------------------------------------
def detect_inport_label(raw, upper):
    """
    Returns a clean standardized label for SBTT/MITE events:

      - ASW MITE
      - ASTAC MITE
      - <SHIP> SBTT
      - SBTT
      - MITE
      - None (not an in-port training event)

    Ship-specific SBTT (e.g. CHOSIN SBTT) is detected by matching ship name.
    """
    up = upper

    # Priority 1: Explicit ASW/ASTAC MITE
    if "ASW MITE" in up:
        return "ASW MITE"

    if "ASTAC MITE" in up:
        return "ASTAC MITE"

    # Priority 2: SBTT including <SHIP> SBTT
    if "SBTT" in up:
        ship = match_ship(raw)
        if ship:
            return f"{ship} SBTT"
        return "SBTT"

    # Priority 3: Generic MITE
    if "MITE" in up:
        return "MITE"

    return None


# ----------------------------------------------------------
# MAIN TORIS PARSER (PATCHED FOR IN-PORT LOGIC)
# ----------------------------------------------------------
def parse_rows(text, year):
    """
    TORIS Sea Duty parser.

    PATCHED BEHAVIOR:
    -----------------
    If any SBTT/MITE training occurs on a date, the ENTIRE DATE becomes:

        In-Port Shore Side Event (<variant>)

    SBTT/MITE rows:
        reason = "In-Port Shore Side Event (<variant>)"

    ALL ship rows + unknown rows:
        reason = "Suppressed by In-Port Shore Side Event (<variant>)"
        or     = "Unknown or Non-Platform Event (<variant>)"

    No valid rows or duplicates are created for that date.
    """

    rows = []
    skipped_duplicates = []
    skipped_unknown = []

    lines = text.splitlines()

    per_date_entries = {}
    date_order = []

    # PASS 1 — Collect entries grouped by date
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
            "date": date,
            "line_index": i,
            "occ_idx": None,
            "ship": None,
            "kind": None,         # valid / unknown
            "is_inport": False,
            "inport_label": None,
        }

        if date not in per_date_entries:
            per_date_entries[date] = []
            date_order.append(date)

        per_date_entries[date].append(entry)

    # Mission priority checker
    def is_mission(e):
        up = e["upper"]
        return any(tag in up for tag in ("M1", "M-1", "M2", "M-2"))

    # PASS 2 — Process dates one by one
    for date in date_order:
        entries = per_date_entries[date]
        inport_variant = None
        occ = 0

        # First pass: detect training types & classify rows
        for e in entries:
            occ += 1
            e["occ_idx"] = occ

            raw = e["raw"]
            up = e["upper"]

            # Detect SBTT/MITE variant
            label = detect_inport_label(raw, up)
            if label:
                e["is_inport"] = True
                e["inport_label"] = label

                # Pick the most specific label (longest)
                if inport_variant is None or len(label) > len(inport_variant):
                    inport_variant = label
            else:
                e["is_inport"] = False

            # Only classify ships for non-inport rows
            if not e["is_inport"]:
                ship = match_ship(raw)
                e["ship"] = ship
                e["kind"] = "valid" if ship else "unknown"

        # --------------------------------------------------
        # CASE 1: IN-PORT SHORE SIDE EVENT ENTIRE DAY
        # --------------------------------------------------
        if inport_variant:
            for e in entries:
                raw = e["raw"]
                occ_idx = e["occ_idx"]

                # SBTT/MITE rows
                if e["is_inport"]:
                    label = e["inport_label"] or inport_variant
                    skipped_unknown.append({
                        "date": date,
                        "raw": raw,
                        "occ_idx": occ_idx,
                        "ship": label,
                        "reason": f"In-Port Shore Side Event ({label})",
                    })
                    continue

                # All other rows: suppressed
                ship = e["ship"] or "UNK"

                if e["kind"] == "unknown":
                    base = "Unknown or Non-Platform Event"
                else:
                    base = "Suppressed by In-Port Shore Side Event"

                skipped_unknown.append({
                    "date": date,
                    "raw": raw,
                    "occ_idx": occ_idx,
                    "ship": ship,
                    "reason": f"{base} ({inport_variant})",
                })

            # No valid rows on in-port days
            continue

        # --------------------------------------------------
        # CASE 2: ORIGINAL BEHAVIOR (NO IN-PORT TRAINING)
        # --------------------------------------------------
        valids = [e for e in entries if e["kind"] == "valid"]

        # No valid rows → all unknown rows become invalid
        if not valids:
            for e in entries:
                if e["kind"] == "unknown":
                    skipped_unknown.append({
                        "date": date,
                        "raw": e["raw"],
                        "occ_idx": e["occ_idx"],
                        "ship": None,
                        "reason": "Unknown or Non-Platform Event",
                    })
            continue

        # Multiple valid rows → apply mission priority
        ships_set = set(e["ship"] for e in valids)

        if len(ships_set) == 1:
            kept = valids[0]
        else:
            mission_valids = [e for e in valids if is_mission(e)]
            if mission_valids:
                kept = sorted(mission_valids, key=lambda x: x["occ_idx"])[0]
            else:
                kept = sorted(valids, key=lambda x: x["occ_idx"])[0]

        # Save valid row
        rows.append({
            "date": date,
            "ship": kept["ship"],
            "occ_idx": kept["occ_idx"],
        })

        # Remaining valids → duplicates
        for e in valids:
            if e is kept:
                continue
            skipped_duplicates.append({
                "date": date,
                "ship": e["ship"],
                "occ_idx": e["occ_idx"],
                "reason": "Duplicate entry for date",
            })

        # Unknown rows remain invalid
        for e in entries:
            if e["kind"] == "unknown":
                skipped_unknown.append({
                    "date": date,
                    "raw": e["raw"],
                    "occ_idx": e["occ_idx"],
                    "ship": None,
                    "reason": "Unknown or Non-Platform Event",
                })

    return rows, skipped_duplicates, skipped_unknown


# ----------------------------------------------------------
# GROUPING LOGIC
# ----------------------------------------------------------
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
