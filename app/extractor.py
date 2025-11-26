import pdfplumber
import re
from datetime import datetime
from app.config import NAME_PREFIX, SIGNATURE_MARKER, SKIP_KEYWORD


def parse_date(s):
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except:
            pass
    return None


def clean_ship_name(raw):
    if not raw:
        return ""
    r = raw
    r = r.replace("þ", " ")
    r = re.sub(r"\(.*?\)", " ", r)
    r = re.sub(r"\bUSS\b", " ", r, flags=re.I)
    r = re.sub(r"\b\d{3,4}\b", " ", r)
    r = re.sub(r"[\d\-]", " ", r)
    r = re.sub(r"\s+", " ", r)
    return r.strip().upper()


def extract_sailors_and_events(pdf_path):
    sailors = []
    current_name = None
    current_events = []

    print("DEBUG: OPENING PDF", pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""

            # detect sailor
            for line in text.split("\n"):
                if line.startswith(NAME_PREFIX):
                    n = line.replace(NAME_PREFIX, "").strip()
                    n = n.split("SSN")[0].strip()

                    if current_name and current_events:
                        sailors.append({"name": current_name, "events": group_by_ship(current_events)})

                    current_name = n
                    current_events = []
                    print("DEBUG: NEW SAILOR =", current_name)
                    break

            # detect table events
            table = page.extract_table()
            if not table:
                continue

            for row in table:
                if not row or not isinstance(row[0], str):
                    continue

                dt = parse_date(row[0])
                if not dt:
                    continue

                ship_raw = " ".join([c for c in row[1:3] if c])

                if SKIP_KEYWORD in ship_raw.upper():
                    continue

                cname = clean_ship_name(ship_raw)
                if cname:
                    current_events.append((dt, cname))
                    print("DEBUG: EVENT", dt, cname)

            # signature = end of sailor
            for line in text.split("\n"):
                if SIGNATURE_MARKER in line:
                    sailors.append({"name": current_name, "events": group_by_ship(current_events)})
                    current_name = None
                    current_events = []
                    break

    print("DEBUG: FINAL SAILORS =", sailors)
    return sailors


def group_by_ship(events):
    ships = {}
    for dt, ship in events:
        ships.setdefault(ship, []).append(dt)

    final = []
    for ship, dates in ships.items():
        dates.sort()
        final.append((ship, dates[0], dates[-1]))

    return final
