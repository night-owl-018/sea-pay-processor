import os
import re
import io
import csv
import zipfile
import tempfile
from collections import deque
from datetime import datetime, timedelta
from difflib import get_close_matches, SequenceMatcher

from flask import Flask, render_template, request, send_from_directory, jsonify
from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

import pytesseract
from pdf2image import convert_from_path

# ------------------------------------------------
# PATH CONFIG
# ------------------------------------------------

DATA_DIR = "/data"
OUTPUT_DIR = "/output"
TEMPLATE_DIR = "/templates"
CONFIG_DIR = "/config"

TEMPLATE = os.path.join(TEMPLATE_DIR, "NAVPERS_1070_613_TEMPLATE.pdf")
RATE_FILE = os.path.join(CONFIG_DIR, "atgsd_n811.csv")
SHIP_FILE = "/app/ships.txt"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

pytesseract.pytesseract.tesseract_cmd = "tesseract"
FONT_NAME = "Times-Roman"
FONT_SIZE = 10

# ------------------------------------------------
# LIVE LOG BUFFER
# ------------------------------------------------

LIVE_LOGS = deque(maxlen=500)

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LIVE_LOGS.append(line)

def clear_logs():
    LIVE_LOGS.clear()
    print("Logs cleared", flush=True)

# ------------------------------------------------
# CLEANUP FUNCTIONS
# ------------------------------------------------

def cleanup_folder(folder_path, folder_name):
    try:
        files_deleted = 0
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                files_deleted += 1
        
        if files_deleted > 0:
            log(f"🗑️ CLEANED {folder_name}: {files_deleted} files deleted")
        return files_deleted
    except Exception as e:
        log(f"❌ CLEANUP ERROR in {folder_name}: {e}")
        return 0

def cleanup_all_folders():
    log("=== STARTING RESET/CLEANUP ===")
    total = 0
    total += cleanup_folder(DATA_DIR, "INPUT/DATA")
    total += cleanup_folder(OUTPUT_DIR, "OUTPUT")
    log(f"✅ RESET COMPLETE: {total} total files deleted")
    log(f"🗑️ CLEARING ALL LOGS...")
    log("=" * 50)
    return total

# ------------------------------------------------
# LOAD RATES
# ------------------------------------------------

def _clean_header(h):
    return h.lstrip("\ufeff").strip().strip('"').lower() if h else ""

def load_rates():
    rates = {}
    if not os.path.exists(RATE_FILE):
        log("RATE FILE MISSING")
        return rates

    with open(RATE_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [_clean_header(h) for h in reader.fieldnames]

        for row in reader:
            last = (row.get("last") or "").upper().strip()
            first = (row.get("first") or "").upper().strip()
            rate = (row.get("rate") or "").upper().strip()
            if last and rate:
                rates[f"{last},{first}"] = rate

    log(f"RATES LOADED: {len(rates)}")
    return rates

RATES = load_rates()

CSV_IDENTITIES = []
for key, rate in RATES.items():
    last, first = key.split(",", 1)
    def normalize_for_id(text):
        t = re.sub(r"\(.*?\)", "", text.upper())
        t = re.sub(r"[^A-Z ]", "", t)
        return " ".join(t.split())
    full_norm = normalize_for_id(f"{first} {last}")
    CSV_IDENTITIES.append((full_norm, rate, last, first))

# ------------------------------------------------
# LOAD SHIP LIST
# ------------------------------------------------

with open(SHIP_FILE, "r", encoding="utf-8") as f:
    SHIP_LIST = [line.strip() for line in f if line.strip()]

def normalize(text):
    text = re.sub(r"\(.*?\)", "", text.upper())
    text = re.sub(r"[^A-Z ]", "", text)
    return " ".join(text.split())

NORMALIZED_SHIPS = {normalize(s): s.upper() for s in SHIP_LIST}
NORMAL_KEYS = list(NORMALIZED_SHIPS.keys())

# ------------------------------------------------
# OCR FUNCTIONS
# ------------------------------------------------

def strip_times(text):
    return re.sub(r"\b[0-2]?\d[0-5]\d\b", "", text)

def ocr_pdf(path):
    images = convert_from_path(path)
    output = ""
    for img in images:
        output += pytesseract.image_to_string(img)
    return output.upper()

# ------------------------------------------------
# NAME EXTRACTION
# ------------------------------------------------

def extract_member_name(text):
    m = re.search(r"NAME:\s*([A-Z\s]+?)\s+SSN", text)
    if not m:
        raise RuntimeError("NAME NOT FOUND")
    return " ".join(m.group(1).split())

# ------------------------------------------------
# SHIP MATCH
# ------------------------------------------------

def match_ship(raw_text):
    candidate = normalize(raw_text)
    words = candidate.split()
    for size in range(len(words), 0, -1):
        for i in range(len(words) - size + 1):
            chunk = " ".join(words[i:i+size])
            match = get_close_matches(chunk, NORMAL_KEYS, n=1, cutoff=0.75)
            if match:
                return NORMALIZED_SHIPS[match[0]]
    return None

# ------------------------------------------------
# DATES (SBTT HANDLED HERE)
# ------------------------------------------------

def extract_year_from_filename(fn):
    m = re.search(r"(20\d{2})", fn)
    return m.group(1) if m else str(datetime.now().year)

def parse_rows(text, year):
    rows = []
    seen_dates = set()
    skipped_duplicates = []
    skipped_unknown = []

    lines = text.splitlines()

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

        cleaned_raw = raw.strip()
        upper_raw = cleaned_raw.upper()

        # ✅ SBTT ALWAYS SKIPPED FROM VALID ROWS
        if "SBTT" in upper_raw:
            sbtt_ship = match_ship(raw) or ""
            label = f"{sbtt_ship} SBTT".strip() if sbtt_ship else "SBTT"
            skipped_unknown.append({"date": date, "raw": label})
            log(f"⚠️ SBTT EVENT, SKIPPING → {date} [{label}]")
            continue

        ship = match_ship(raw)

        if not ship:
            skipped_unknown.append({"date": date, "raw": cleaned_raw})
            log(f"⚠️ UNKNOWN SHIP/EVENT, SKIPPING → {date} [{cleaned_raw}]")
            continue

        if date in seen_dates:
            skipped_duplicates.append({"date": date, "ship": ship})
            log(f"⚠️ DUPLICATE DATE FOUND, DISCARDING → {date} ({ship})")
            continue

        rows.append({"date": date, "ship": ship})
        seen_dates.add(date)

    return rows, skipped_duplicates, skipped_unknown

# ------------------------------------------------
# GROUPING
# ------------------------------------------------

def group_by_ship(rows):
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

# ------------------------------------------------
# PROCESS (SUMMARY FORMAT FIXED EXACTLY)
# ------------------------------------------------

def process_all():
    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]

    if not files:
        log("NO INPUT FILES")
        return

    log("=== PROCESS STARTED ===")
    summary_lines = []
    width = 69

    for file in files:
        log(f"OCR → {file}")
        path = os.path.join(DATA_DIR, file)
        raw = strip_times(ocr_pdf(path))

        try:
            name = extract_member_name(raw)
        except:
            continue

        year = extract_year_from_filename(file)
        rows, skipped_dupe, skipped_unknown = parse_rows(raw, year)
        groups = group_by_ship(rows)

        csv_id = lookup_csv_identity(name)
        display_name = f"{csv_id[0]} {csv_id[2]} {csv_id[1]}" if csv_id else name

        summary_lines.append("=" * width)
        summary_lines.append(display_name.upper())
        summary_lines.append("=" * width)
        summary_lines.append("")
        summary_lines.append("VALID SEA PAY PERIODS")
        summary_lines.append("-" * width)

        total_days = 0
        for g in groups:
            days = (g["end"] - g["start"]).days + 1
            total_days += days
            summary_lines.append(
                f"{g['ship']:<18} : FROM {g['start'].strftime('%m/%d/%Y')} TO {g['end'].strftime('%m/%d/%Y')}".ljust(54)
                + f"({days} DAYS)"
            )

        summary_lines.append("")
        summary_lines.append(f"TOTAL VALID DAYS: {total_days}")
        summary_lines.append("")
        summary_lines.append("-" * width)
        summary_lines.append("INVALID / EXCLUDED EVENTS / UNRECOGNIZED / NON-SHIP ENTRIES")

        for s in skipped_unknown:
            clean = re.sub(r"[^A-Z ]", " ", s["raw"].upper())
            clean = " ".join(clean.split())

            if "ASTAC" in clean and "MITE" in clean:
                summary_lines.append(f"  ASTAC MITE : {s['date']}")
            elif "ASW" in clean and "MITE" in clean:
                summary_lines.append(f"  ASW MITE : {s['date']}")
            elif "SBTT" in clean:
                summary_lines.append(f"  {clean} : {s['date']}")
            else:
                summary_lines.append(f"  {s['date']}  {s['raw']}")

        summary_lines.append("")
        summary_lines.append("-" * width)
        summary_lines.append("DUPLICATE DATE CONFLICTS")

        for d in skipped_dupe:
            summary_lines.append(f"  {d['date']}  {d['ship']}")

        summary_lines.append("")
        summary_lines.append("")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, f"SeaPay_Summary_{ts}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))
    log(f"📝 SUMMARY FILE CREATED → {os.path.basename(path)}")

# ------------------------------------------------
# FLASK APP (UNCHANGED)
# ------------------------------------------------

app = Flask(__name__, template_folder="web/frontend")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        for f in request.files.getlist("files"):
            f.save(os.path.join(DATA_DIR, f.filename))
        process_all()
    return render_template("index.html", logs="\n".join(LIVE_LOGS))

@app.route("/download_summary")
def download_summary():
    files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.startswith("SeaPay_Summary_")])
    return send_from_directory(OUTPUT_DIR, files[-1], as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
