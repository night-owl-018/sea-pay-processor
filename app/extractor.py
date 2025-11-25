import pdfplumber
import re
from datetime import datetime
from app.config import NAME_PREFIX, SIGNATURE_MARKER, SKIP_KEYWORD


# ---------------------- Helpers ---------------------- #

def parse_date(date_str):
    """Parse M/D/YYYY or M/D/YY."""
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def clean_ship_name(raw):
    """
    Clean the ship name extracted from table columns.

    This version is HARDENED:

    Removes:
    - USS prefix
    - timestamps (0000, 2359, 08:45, 18-06-00, ISO timestamps)
    - underscores
    - parentheses blocks like (ASW C-1) (CG-65)
    - checkmark 'þ'
    - all numbers
    - all hyphens
    - leftover symbols
    - multiple spaces

    Keeps ONLY actual ship-name alphabet words.
    """

    if not raw:
        return ""

    # Normalize junk characters
    raw = raw.replace("þ", " ").replace("*", " ").replace("_", " ")

    # Remove parentheses content
    raw = re.sub(r"\(.*?\)", " ", raw)

    # Remove USS prefix
    raw = re.sub(r"\bUSS\b", " ", raw, flags=re.IGNORECASE)

    # Remove times like 0000, 2359, 0815, etc.
    raw = re.sub(r"\b\d{3,4}\b", " ", raw)

    # Remove ISO timestamps like 2025-11-22T1300
    raw = re.sub(r"\d{4}-\d{2}-\d{2}T\d{3,4}", " ", raw)

    # Remove date/time fragments (18-06-00)
    raw = re.sub(r"\d{1,2}-\d{1,2}-\d{1,2}", " ", raw)

    # Remove all digits and hyphens
    raw = re.sub(r"[\d\-]", " ", raw)

    # Extract ONLY alphabetic words — safest approach
    words = re.findall(r"[A-Za-z]+", raw)

    if not words:
        return ""

    cleaned = " ".join(words).upper()

    return cleaned.strip()


def group_by_ship(events):
    """
    events: list[(date, ship_name)]
    Returns: list[(ship, start_date, end_date)]
    """
    grouped = {}
    for dt, ship in events:
        grouped.setdefault(ship, []).append(dt)

    final = []
    for ship, dates in grouped.items():
        sorted_dates = sorted(dates)
        final.append((ship, sorted_dates[0], sorted_dates[-1]))

    return final


# ---------------------- Core Parser ---------------------- #

def extract_sailors_and_events(pdf_path):
    sailors = []

    current_name = None
    current_events = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:

            text = page.extract_text() or ""
            lines = text.split("\n")

            # 1. Detect sailor name line
            for line in lines:
                if line.startswith(NAME_PREFIX):
                    extracted = line[len(NAME_PREFIX):].strip()
                    if "SSN" in extracted:
                        extracted = extracted.split("SSN")[0].strip()

                    # Save previous sailor before starting new one
                    if current_name and current_events:
                        sailors.append({
                            "name": current_name,
                            "events": group_by_ship(current_events)
                        })

                    current_name = extracted
                    current_events = []
                    break

            # 2. Table extraction
            table = page.extract_table()
            if not table:
                continue

            for row in table:
                if not row:
                    continue

                date_col = row[0]
                if not date_col or not isinstance(date_col, str):
                    continue

                dt = parse_date(date_col.strip())
                if not dt:
                    continue

                # Combine ship fields
                ship_parts = row[1:3]
                ship_raw = " ".join([p for p in ship_parts if p])

                if not ship_raw:
                    continue

                # Skip MITE rows
                if SKIP_KEYWORD in ship_raw.upper():
                    continue

                ship_clean = clean_ship_name(ship_raw)
                if ship_clean:
                    current_events.append((dt, ship_clean))

            # 3. Signature ends sailor
            for line in lines:
                if SIGNATURE_MARKER in line and current_name:
                    sailors.append({
                        "name": current_name,
                        "events": group_by_ship(current_events)
                    })
                    current_name = None
                    current_events = []
                    break

    return sailors
