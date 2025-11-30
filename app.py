import os
import re
import io
import csv
import zipfile
from datetime import datetime, timedelta
from difflib import get_close_matches
from collections import defaultdict

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    send_from_directory,
    jsonify,
    Response,
    url_for,
)

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

import pytesseract
from pdf2image import convert_from_path


# ------------------------------------------------
# APP INIT
# ------------------------------------------------
app = Flask(__name__)

# ------------------------------------------------
# DIRECTORIES INSIDE CONTAINER
# ------------------------------------------------
DATA_DIR = "/data"
TEMPLATE_DIR = "/templates"
CONFIG_DIR = "/config"
OUTPUT_DIR = "/output"

DEFAULT_TEMPLATE = os.path.join(TEMPLATE_DIR, "NAVPERS_1070_613_TEMPLATE.pdf")
DEFAULT_RATES_CSV = os.path.join(CONFIG_DIR, "atgsd_n811.csv")

for d in [DATA_DIR, TEMPLATE_DIR, CONFIG_DIR, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

# ------------------------------------------------
# OCR CONFIG
# ------------------------------------------------
pytesseract.pytesseract.tesseract_cmd = "tesseract"

# ------------------------------------------------
# PDF FONT
# ------------------------------------------------
FONT_NAME = "Times-Roman"
FONT_SIZE = 10

# ------------------------------------------------
# SHIP LIST
# ------------------------------------------------
SHIP_LIST = [
    "America", "Anchorage", "Arleigh Burke", "Arlington", "Ashland", "Augusta",
    "Bainbridge", "Barry", "Bataan", "Beloit", "Benfold", "Billings", "Blue Ridge",
    "Boxer", "Bulkeley", "Canberra", "Cape St. George", "Carl M. Levin", "Carney",
    "Carter Hall", "Chafee", "Charleston", "Chief", "Chosin", "Chung-Hoon",
    "Cincinnati", "Cole", "Comstock", "Cooperstown", "Curtis Wilbur",
    "Daniel Inouye", "Decatur", "Delbert D. Black", "Dewey", "Donald Cook", "Essex",
    "Farragut", "Fitzgerald", "Forrest Sherman", "Fort Lauderdale", "Fort Worth",
    "Frank E. Petersen Jr.", "Gabrielle Giffords", "Germantown", "Gettysburg",
    "Gonzalez", "Gravely", "Green Bay", "Gridley", "Gunston Hall", "Halsey",
    "Harpers Ferry", "Higgins", "Hopper", "Howard", "Indianapolis", "Iwo Jima",
    "Jackson", "Jack H. Lucas", "James E. Williams", "Jason Dunham",
    "John Basilone", "John Finn", "John P. Murtha", "John Paul Jones",
    "John S. McCain", "Kansas City", "Kearsarge", "Kidd", "Kingsville",
    "Laboon", "Lake Erie", "Lassen", "Lenah Sutcliffe Higbee",
    "Mahan", "Makin Island", "Manchester", "Marinette", "Mason", "McCampbell",
    "McFaul", "Mesa Verde", "Michael Monsoor", "Michael Murphy", "Milius",
    "Minneapolis-Saint Paul", "Mitscher", "Mobile", "Momsen", "Montgomery",
    "Mount Whitney", "Mustin", "Nantucket", "New Orleans", "New York", "Nitze",
    "O'Kane", "Oak Hill", "Oakland", "Omaha", "Oscar Austin", "Patriot",
    "Paul Hamilton", "Paul Ignatius", "Pearl Harbor", "Pinckney", "Pioneer",
    "Porter", "Portland", "Preble", "Princeton", "Rafael Peralta", "Ralph Johnson",
    "Ramage", "Richard M. McCool Jr.", "Robert Smalls", "Roosevelt", "Ross",
    "Rushmore", "Russell", "Sampson", "San Antonio", "San Diego", "Santa Barbara",
    "Savannah", "Shiloh", "Shoup", "Somerset", "Spruance", "St. Louis", "Sterett",
    "Stethem", "Stockdale", "Stout", "The Sullivans", "Tortuga", "Tripoli",
    "Truxtun", "Tulsa", "Warrior", "Wasp", "Wayne E. Meyer",
    "William P. Lawrence", "Winston S. Churchill", "Wichita", "Zumwalt",
]


def normalize(text: str) -> str:
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"[^A-Z ]", "", text.upper())
    return " ".join(text.split())


NORMALIZED_SHIPS = {normalize(s): s.upper() for s in SHIP_LIST}
NORMAL_KEYS = list(NORMALIZED_SHIPS.keys())

# ------------------------------------------------
# JOB HISTORY (IN-MEMORY)
# ------------------------------------------------
JOB_HISTORY = []
NEXT_JOB_ID = 1  # simple counter, resets on container restart


# ------------------------------------------------
# CORE FUNCTIONS
# ------------------------------------------------
def strip_times(text: str) -> str:
    return re.sub(r"\b[0-2]?\d[0-5]\d\b", "", text)


def extract_member_name(text: str) -> str:
    m = re.search(r"NAME:\s*([A-Z\s]+?)\s+SSN", text)
    if not m:
        raise RuntimeError("NAME not found.")
    return " ".join(m.group(1).split())


def match_ship(raw_text: str):
    candidate = normalize(raw_text)
    if not candidate:
        return None

    words = candidate.split()
    for size in range(len(words), 0, -1):
        for i in range(len(words) - size + 1):
            chunk = " ".join(words[i:i + size])
            match = get_close_matches(chunk, NORMAL_KEYS, n=1, cutoff=0.75)
            if match:
                return NORMALIZED_SHIPS[match[0]]
    return None


def extract_year_from_filename(path: str) -> str:
    m = re.search(r"(20\d{2})", os.path.basename(path))
    return m.group(1) if m else str(datetime.now().year)


def parse_rows(text: str, year: str):
    rows = []
    seen = set()
    lines = text.splitlines()

    for i, line in enumerate(lines):
        m = re.match(r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", line)
        if not m:
            continue

        mm, dd, yy = m.groups()
        y = ("20" + yy) if (yy and len(yy) == 2) else (yy if yy else year)
        date = f"{mm.zfill(2)}/{dd.zfill(2)}/{y}"

        raw = line[m.end():]
        if i + 1 < len(lines):
            raw += " " + lines[i + 1]

        ship = match_ship(raw)
        if not ship:
            continue

        key = (date, ship)
        if key not in seen:
            rows.append({"date": date, "ship": ship})
            seen.add(key)

    return rows


def group_by_ship(rows):
    groups = defaultdict(list)
    for r in rows:
        dt = datetime.strptime(r["date"], "%m/%d/%Y")
        groups[r["ship"]].append(dt)

    results = []
    for ship, dates in groups.items():
        dates = sorted(set(dates))
        start = prev = dates[0]
        for day in dates[1:]:
            if day == prev + timedelta(days=1):
                prev = day
            else:
                results.append(
                    {
                        "ship": ship,
                        "start": start.strftime("%m/%d/%Y"),
                        "end": prev.strftime("%m/%d/%Y"),
                    }
                )
                start = prev = day
        results.append(
            {
                "ship": ship,
                "start": start.strftime("%m/%d/%Y"),
                "end": prev.strftime("%m/%d/%Y"),
            }
        )
    return results


def load_rates(rate_file: str, log):
    rates = {}

    if not os.path.exists(rate_file):
        log(f"[RATES] CSV not found: {rate_file}")
        return rates

    log(f"[RATES] Loading from {rate_file}")

    with open(rate_file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            log("[RATES] No header row.")
            return rates

        def _clean_header(h: str) -> str:
            if h is None:
                return ""
            return h.lstrip("\ufeff").strip().strip('"').lower()

        reader.fieldnames = [_clean_header(h) for h in reader.fieldnames]

        for raw_row in reader:
            row = {}
            for k, v in raw_row.items():
                key = _clean_header(k)
                if not key:
                    continue
                row[key] = (v or "").strip()

            last = row.get("last", "").upper()
            first = row.get("first", "").upper()
            rate = row.get("rate", "").upper()

            if not last or not rate:
                continue

            rates[f"{last},{first}"] = rate

    log(f"[RATES] Loaded {len(rates)} entries.")
    return rates


def get_rate(name: str, rates: dict) -> str:
    parts = normalize(name).split()
    if len(parts) < 2:
        return ""

    first = parts[0]
    last = parts[-1]

    key = f"{last},{first}"
    if key in rates:
        return rates[key]

    for k in rates:
        if k.startswith(last + ","):
            return rates[k]

    return ""


def ocr_pdf(path: str, log) -> str:
    log(f"[OCR] Reading {path}")
    images = convert_from_path(path)
    out = ""
    for img in images:
        out += pytesseract.image_to_string(img)
    return out.upper()


def make_pdf(group, name, rate, template_pdf: str, output_dir: str, log):
    start = group["start"]
    end = group["end"]
    ship = group["ship"]

    parts = name.split()
    last = parts[-1]
    first = " ".join(parts[:-1])

    prefix = f"{rate}_" if rate else ""
    filename = (
        f"{prefix}{last}_{first}_{ship}_{start.replace('/','-')}_TO_{end.replace('/','-')}.pdf"
    )
    filename = filename.replace(" ", "_")

    path = os.path.join(output_dir, filename)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont(FONT_NAME, 10)

    # HEADER
    c.drawString(39, 689, "AFLOAT TRAINING GROUP SAN DIEGO (UIC. 49365)")
    c.drawString(373, 671, "X")
    c.setFont(FONT_NAME, 8)
    c.drawString(39, 650, "ENTITLEMENT")
    c.drawString(345, 641, "OPNAVINST 7220.14")

    # BODY
    c.setFont(FONT_NAME, 10)
    if rate:
        c.drawString(39, 41, f"{rate} {last}, {first}")
    else:
        c.drawString(39, 41, f"{last}, {first}")

    c.drawString(38.84, 595, f"____. REPORT CAREER SEA PAY FROM {start} TO {end}.")
    c.drawString(
        64,
        571,
        f"Member performed eight continuous hours per day on-board: {ship} Category A vessel.",
    )

    # CERTIFYING BLOCK
    c.drawString(356.26, 499.5, "_________________________")
    c.drawString(363.8, 487.5, "Certifying Official & Date")
    c.drawString(356.26, 427.5, "_________________________")
    c.drawString(384.1, 415.2, "FI MI Last Name")
    c.drawString(38.8, 83, "SEA PAY CERTIFIER")
    c.drawString(503.5, 41, "USN AD")

    c.save()
    buf.seek(0)

    overlay = PdfReader(buf)
    template = PdfReader(template_pdf)

    base = template.pages[0]
    base.merge_page(overlay.pages[0])

    writer = PdfWriter()
    writer.add_page(base)

    for i in range(1, len(template.pages)):
        writer.add_page(template.pages[i])

    os.makedirs(output_dir, exist_ok=True)
    with open(path, "wb") as f:
        writer.write(f)

    log(f"[PDF] Created {path}")
    return path


def merge_with_bookmarks(output_dir: str, log):
    pdfs = sorted(
        f
        for f in os.listdir(output_dir)
        if f.lower().endswith(".pdf") and not f.startswith("MASTER")
    )

    if not pdfs:
        log("[MERGE] No PDFs to merge.")
        return None

    writer = PdfWriter()
    page = 0
    for file in pdfs:
        full = os.path.join(output_dir, file)
        reader = PdfReader(full)
        writer.add_outline_item(file.replace(".pdf", ""), page)
        for p in reader.pages:
            writer.add_page(p)
            page += 1

    out_path = os.path.join(output_dir, "MASTER_SEA_PAY_PACKET.pdf")
    with open(out_path, "wb") as f:
        writer.write(f)

    log(f"[MERGE] Master packet created: {out_path}")
    return out_path


def run_processor():
    """Run a full job and store it in JOB_HISTORY."""
    global NEXT_JOB_ID, JOB_HISTORY

    logs = []
    had_error = False

    def log(msg):
        nonlocal had_error
        if msg.startswith("[ERROR]") or msg.startswith("[WARN]"):
            had_error = True
        print(msg)
        logs.append(msg)

    log(f"[CONFIG] DATA       = {DATA_DIR}")
    log(f"[CONFIG] TEMPLATE   = {DEFAULT_TEMPLATE}")
    log(f"[CONFIG] RATE CSV   = {DEFAULT_RATES_CSV}")
    log(f"[CONFIG] OUTPUT DIR = {OUTPUT_DIR}")

    rates = load_rates(DEFAULT_RATES_CSV, log)

    if not os.path.isdir(DATA_DIR):
        log(f"[ERROR] Data dir not found: {DATA_DIR}")
    else:
        files = [
            f
            for f in os.listdir(DATA_DIR)
            if f.lower().endswith(".pdf") and "navpers" not in f.lower()
        ]

        if not files:
            log("[PROCESS] No input PDFs found.")
        else:
            for file in files:
                path = os.path.join(DATA_DIR, file)
                log(f"[PROCESS] ---- {file} ----")

                raw = strip_times(ocr_pdf(path, log))

                try:
                    name = extract_member_name(raw)
                    log(f"[NAME] {name}")
                except RuntimeError as e:
                    log(f"[ERROR] {e}")
                    continue

                year = extract_year_from_filename(path)
                rows = parse_rows(raw, year)
                groups = group_by_ship(rows)
                rate = get_rate(name, rates)

                if groups:
                    for g in groups:
                        make_pdf(g, name, rate, DEFAULT_TEMPLATE, OUTPUT_DIR, log)
                else:
                    log("[WARN] No valid sea-pay rows found in this file.")

    merge_with_bookmarks(OUTPUT_DIR, log)
    log("✅ JOB COMPLETE")

    # record job
    job_id = NEXT_JOB_ID
    NEXT_JOB_ID += 1
    status = "ERROR" if had_error else "OK"

    job = {
        "id": job_id,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "logs": logs,
    }
    JOB_HISTORY.insert(0, job)
    return job


# ------------------------------------------------
# ROUTES
# ------------------------------------------------
@app.route("/")
def index():
    inspect_rate = request.args.get("inspect_rate")
    rate_preview = None
    inspected_file = None

    if inspect_rate:
        inspected_file = inspect_rate
        path = os.path.join(CONFIG_DIR, inspect_rate)
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = []
                for i, row in enumerate(reader):
                    rows.append(row)
                    if i >= 20:
                        break
                rate_preview = rows

    return render_template(
        "index.html",
        template_files=sorted(os.listdir(TEMPLATE_DIR)),
        rate_files=sorted(os.listdir(CONFIG_DIR)),
        data_files=sorted(os.listdir(DATA_DIR)),
        output_files=sorted(os.listdir(OUTPUT_DIR)),
        job_history=JOB_HISTORY,
        rate_preview=rate_preview,
        inspected_file=inspected_file,
    )


# ---------- UPLOADS ----------

@app.route("/upload-template", methods=["POST"])
def upload_template():
    f = request.files.get("file")
    if f and f.filename:
        f.save(os.path.join(TEMPLATE_DIR, os.path.basename(f.filename)))
    return redirect(url_for("index"))


@app.route("/upload-rate", methods=["POST"])
def upload_rate():
    f = request.files.get("file")
    if f and f.filename:
        f.save(os.path.join(CONFIG_DIR, os.path.basename(f.filename)))
    return redirect(url_for("index"))


@app.route("/upload-data", methods=["POST"])
def upload_data():
    for f in request.files.getlist("files"):
        if f and f.filename:
            f.save(os.path.join(DATA_DIR, os.path.basename(f.filename)))
    return redirect(url_for("index"))


@app.route("/upload-zip-data", methods=["POST"])
def upload_zip_data():
    z = request.files.get("zipfile")
    if not z or not z.filename:
        return redirect(url_for("index"))

    os.makedirs(DATA_DIR, exist_ok=True)

    with zipfile.ZipFile(z.stream) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            # drop any path, keep only filename
            name = os.path.basename(member.filename)
            if not name:
                continue
            with zf.open(member) as src, open(
                os.path.join(DATA_DIR, name), "wb"
            ) as dst:
                dst.write(src.read())

    return redirect(url_for("index"))


# ---------- FILE MANAGEMENT ----------

FOLDER_MAP = {
    "data": DATA_DIR,
    "templates": TEMPLATE_DIR,
    "config": CONFIG_DIR,
    "output": OUTPUT_DIR,
}


@app.route("/delete/<folder>/<name>", methods=["POST"])
def delete_file(folder, name):
    base = FOLDER_MAP.get(folder)
    if not base:
        return redirect(url_for("index"))
    safe_name = os.path.basename(name)
    path = os.path.join(base, safe_name)
    if os.path.exists(path):
        os.remove(path)
    return redirect(url_for("index"))


@app.route("/rename/<folder>/<name>", methods=["POST"])
def rename_file(folder, name):
    base = FOLDER_MAP.get(folder)
    if not base:
        return redirect(url_for("index"))

    new_name = request.form.get("new_name", "").strip()
    if not new_name:
        return redirect(url_for("index"))

    safe_old = os.path.basename(name)
    safe_new = os.path.basename(new_name)

    old_path = os.path.join(base, safe_old)
    new_path = os.path.join(base, safe_new)

    if os.path.exists(old_path):
        os.rename(old_path, new_path)

    return redirect(url_for("index"))


# ---------- DOWNLOAD / PREVIEW ----------

@app.route("/download-output/<name>")
def download_output(name):
    safe_name = os.path.basename(name)
    return send_from_directory(OUTPUT_DIR, safe_name, as_attachment=True)


@app.route("/preview-template/<name>")
def preview_template(name):
    safe_name = os.path.basename(name)
    return send_from_directory(TEMPLATE_DIR, safe_name)


@app.route("/download-log/<int:job_id>")
def download_log(job_id):
    for job in JOB_HISTORY:
        if job["id"] == job_id:
            text = "\n".join(job["logs"])
            return Response(
                text,
                mimetype="text/plain",
                headers={"Content-Disposition": f"attachment; filename=job_{job_id}_log.txt"},
            )
    return "Job not found", 404


# ---------- API: RUN WITH PROGRESS ----------

@app.route("/run", methods=["POST"])
def api_run():
    job = run_processor()
    return jsonify(
        {
            "job_id": job["id"],
            "status": job["status"],
            "logs": job["logs"],
        }
    )


# ------------------------------------------------
# START
# ------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
