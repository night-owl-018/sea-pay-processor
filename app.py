import os, re, io, csv
from datetime import datetime, timedelta
from difflib import get_close_matches
from flask import Flask, render_template, request, redirect, send_from_directory
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import pytesseract
from pdf2image import convert_from_path

# ------------------ APP ------------------
app = Flask(__name__)

ROOT = os.path.dirname(os.path.abspath(__file__))

DATA_DIR       = "/data"
OUTPUT_DIR     = "/output"
TEMPLATE_DIR   = "/templates"
TEMPLATE_PDF   = os.path.join(TEMPLATE_DIR, "NAVPERS_1070_613_TEMPLATE.pdf")
CSV_FILE       = os.path.join(ROOT, "atgsd_n811.csv")
SHIP_FILE      = os.path.join(ROOT, "ships.txt")

pytesseract.pytesseract.tesseract_cmd = "tesseract"
FONT = "Times-Roman"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)

# ---------------- SHIPS ------------------
def load_ships():
    if not os.path.exists(SHIP_FILE):
        raise FileNotFoundError("ships.txt missing")
    with open(SHIP_FILE,"r",encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

SHIP_LIST = load_ships()
NORMALIZED = { re.sub(r"[^A-Z ]","",s.upper()):s.upper() for s in SHIP_LIST }
SHIP_KEYS = list(NORMALIZED.keys())

def normalize(t):
    return re.sub(r"[^A-Z ]","",t.upper()).strip()

# ---------------- RATES ------------------
def load_rates(log):
    rates = {}
    if not os.path.exists(CSV_FILE):
        log("[RATES] Missing CSV")
        return rates

    with open(CSV_FILE,newline="",encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            last = (row.get("last") or "").upper().strip()
            first = (row.get("first") or "").upper().strip()
            rate = (row.get("rate") or "").upper().strip()
            if last and rate:
                rates[f"{last},{first}"] = rate

    log(f"[RATES] Loaded {len(rates)}")
    return rates

def get_rate(name,rates):
    parts = normalize(name).split()
    if len(parts)<2: return ""
    first,last = parts[0],parts[-1]
    return rates.get(f"{last},{first}","")

# ---------------- OCR ------------------
def ocr_pdf(path, log):
    log(f"[OCR] {path}")
    imgs = convert_from_path(path)
    return "".join(pytesseract.image_to_string(i) for i in imgs).upper()

def strip_times(t):
    return re.sub(r"\b\d{3,4}\b","",t)

# ---------------- PARSE ------------------
def extract_name(text):
    m = re.search(r"NAME:\s*([A-Z\s]+?)\s+SSN",text)
    if not m: raise RuntimeError("NAME not found")
    return " ".join(m.group(1).split())

def match_ship(text):
    words = normalize(text).split()
    for size in range(len(words),0,-1):
        for i in range(len(words)-size+1):
            chunk = " ".join(words[i:i+size])
            hit = get_close_matches(chunk, SHIP_KEYS, n=1, cutoff=0.75)
            if hit: return NORMALIZED[hit[0]]

def parse_rows(text,year):
    rows,seen=[],set()
    lines=text.splitlines()
    for i,l in enumerate(lines):
        m=re.match(r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?",l)
        if not m: continue
        mm,dd,yy=m.groups()
        y=("20"+yy) if yy and len(yy)==2 else yy if yy else year
        date=f"{mm.zfill(2)}/{dd.zfill(2)}/{y}"
        raw=l[m.end():]+" "+(lines[i+1] if i+1<len(lines) else "")
        ship=match_ship(raw)
        if ship and (date,ship) not in seen:
            rows.append({"date":date,"ship":ship})
            seen.add((date,ship))
    return rows

def group_by_ship(rows):
    out={}
    for r in rows:
        dt=datetime.strptime(r["date"],"%m/%d/%Y")
        out.setdefault(r["ship"],[]).append(dt)
    groups=[]
    for ship,dates in out.items():
        dates=sorted(set(dates))
        start=prev=dates[0]
        for d in dates[1:]:
            if d==prev+timedelta(days=1): prev=d
            else:
                groups.append({"ship":ship,"start":start,"end":prev})
                start=prev=d
        groups.append({"ship":ship,"start":start,"end":prev})
    return groups

# ---------------- PDF ------------------
def make_pdf(group,name,rate,log):
    start = group["start"].strftime("%m/%d/%Y")
    end   = group["end"].strftime("%m/%d/%Y")
    ship  = group["ship"]
    last  = name.split()[-1]
    first = " ".join(name.split()[:-1])

    prefix=f"{rate}_" if rate else ""
    fname=f"{prefix}{last}_{first}_{ship}_{start}_TO_{end}.pdf".replace(" ","_")
    out=os.path.join(OUTPUT_DIR,fname)

    buf=io.BytesIO()
    c=canvas.Canvas(buf,pagesize=letter)
    c.setFont(FONT,10)

    c.drawString(39,689,"AFLOAT TRAINING GROUP SAN DIEGO (UIC. 49365)")
    c.drawString(373,671,"X")
    c.setFont(FONT,8)
    c.drawString(39,650,"ENTITLEMENT")
    c.drawString(345,641,"OPNAVINST 7220.14")

    c.setFont(FONT,10)
    c.drawString(39,41,f"{rate} {last}, {first}" if rate else f"{last}, {first}")
    c.drawString(38.8,595,f"____. REPORT CAREER SEA PAY FROM {start} TO {end}.")
    c.drawString(64,571,f"Member performed eight continuous hours per day on-board: {ship} Category A vessel.")
    c.drawString(356,500,"_________________________")
    c.drawString(364,488,"Certifying Official & Date")
    c.drawString(356,428,"_________________________")
    c.drawString(384,415,"FI MI Last Name")
    c.drawString(38.8,83,"SEA PAY CERTIFIER")
    c.drawString(503,41,"USN AD")

    c.save()
    buf.seek(0)
    overlay=PdfReader(buf)
    tmpl=PdfReader(TEMPLATE_PDF)

    base=tmpl.pages[0]
    base.merge_page(overlay.pages[0])

    w=PdfWriter()
    w.add_page(base)
    for i in range(1,len(tmpl.pages)):
        w.add_page(tmpl.pages[i])

    with open(out,"wb") as f: w.write(f)
    log(f"[PDF] {fname}")

# ---------------- RUN ------------------
def run():
    logs=[]
    log=lambda m:logs.append(m)

    rates=load_rates(log)

    for f in os.listdir(DATA_DIR):
        if not f.lower().endswith(".pdf"): continue
        path=os.path.join(DATA_DIR,f)
        raw=strip_times(ocr_pdf(path,log))
        try:
            name=extract_name(raw)
            log(f"[NAME] {name}")
        except:
            log("[ERROR] Name not found"); continue
        year=re.search(r"(20\d{2})",f).group(1) if re.search(r"(20\d{2})",f) else str(datetime.now().year)
        for g in group_by_ship(parse_rows(raw,year)):
            rate=get_rate(name,rates)
            make_pdf(g,name,rate,log)

    return logs

# ---------------- WEB ------------------
@app.route("/",methods=["GET","POST"])
def index():
    logs=[]
    if request.method=="POST":
        logs=run()
    return render_template("index.html",
        data=os.listdir(DATA_DIR),
        template=os.listdir(TEMPLATE_DIR),
        output=os.listdir(OUTPUT_DIR),
        logs="\n".join(logs))

@app.route("/upload",methods=["POST"])
def upload():
    category=request.form["type"]
    file=request.files["file"]
    dest={"data":DATA_DIR,"template":TEMPLATE_DIR}[category]
    file.save(os.path.join(dest,file.filename))
    return redirect("/")

@app.route("/download/<name>")
def dl(name):
    return send_from_directory(OUTPUT_DIR,name,as_attachment=True)

@app.route("/delete/<folder>/<name>")
def delete(folder,name):
    os.remove(f"/{folder}/{name}")
    return redirect("/")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080)
