import pdfplumber
import re
from datetime import datetime
from app.config import NAME_PREFIX, SIGNATURE_MARKER, SKIP_KEYWORD


def parse_date(date_str):
    """Parse M/D/YYYY or M/D/YY from SEA DUTY CERT sheet."""
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def clean_event_name(raw: str) -> str:
    """
    Clean messy event names coming from the SEA DUTY CERT sheet.
    Handles:
    - Multi-line names ("PAUL\nHAMILTON")
    - Checkmarks "þ"
    - Times (0000 2359)
    - Parentheses "(ASW T-1)"
    - Extra spacing
    """

    # Remove checkmark glyph
    raw = raw.replace("þ", " ")

    # Remove everything in parentheses: (ASW T-1)
    raw = re.sub(r"\(.*?\)", " ", raw)

    # Remove time blocks like 0000 2359, 0800 1600, etc.
    raw = re.sub(r"\b\d{3,4}\b", " ", raw)

    # Remove asterisks
    raw = raw.replace("*", " ")

    # Replace newlines with space (important!)
    raw = raw.replace("\n", " ")

    # Collapse double spaces
    raw = re.sub(r"\s+", " ", raw)

    # Final clean + uppercase
    cleaned = raw.strip().upper()

    return cleaned


def group_events_by_ship(events):
    """
    events: list[(date, raw_event_string)]

    Each unique ship gets:
    - Start date (min)
    - End date (max)
    - One PG-13 output
    """
    grouped = {}

    for dt, raw in events:
        ship = clean_event_name(raw)
        if not ship:
            continue
        grouped.setdefault(ship, []).append(dt)

    result = []
    for ship, dates in grouped.items():
        dates = sorted(dates)
        result.append((ship, dates[0], dates[-1]))

    return result


def extract_sailors_and_events(pdf_path):
    """
    Reads SEA DUTY CERT PDF and produces:

    [
      {
        "name": "FRANK HATTEN",
        "events": [
            ("PAUL HAMILTON", start, end),
            ("CHOSIN", start, end),
            ("ASHLAND", start, end)
        ]
      }
    ]
    """

    sailors = []
    current_name = None
    current_events = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for raw_line in text.split("\n"):
                line = raw_line.strip()

                # 1. NAME line detection
                if line.startswith(NAME_PREFIX):
                    after = line[len(NAME_PREFIX):].strip()
                    if "SSN" in after:
                        name_part = after.split("SSN", 1)[0].strip()
                    else:
                        name_part = after

                    # Save previous sailor
                    if current_name and current_events:
                        sailors.append({
                            "name": current_name,
                            "events": group_events_by_ship(current_events)
                        })

                    current_name = name_part
                    current_events = []
                    continue

                # 2. Event row detection: START WITH A DATE
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    date_candidate, rest = parts
                    dt = parse_date(date_candidate)

                    if dt and current_name:
                        # Skip MITE events
                        if SKIP_KEYWORD in rest.upper():
                            continue

                        # Collect event raw text (even if multiline)
                        current_events.append((dt, rest))
                        continue

                # 3. Signature block = end of sailor
                if SIGNATURE_MARKER in line and current_name:
                    sailors.append({
                        "name": current_name,
                        "events": group_events_by_ship(current_events)
                    })
                    current_name = None
                    current_events = []

    return sailors
