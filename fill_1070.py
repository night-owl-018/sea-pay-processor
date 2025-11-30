import os
import io
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import pytesseract
from pdf2image import convert_from_path

# ------------------------------------------------
# CONFIG (DOCKER-SAFE)
# ------------------------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))

# OCR Engine
pytesseract.pytesseract.tesseract_cmd = "tesseract"

# Paths (env-driven)
BASE = os.environ.get("SEA_PAY_INPUT", os.path.join(ROOT, "Data"))
TEMPLATE = os.environ.get(
    "SEA_PAY_TEMPLATE",
    os.path.join(ROOT, "pdf_template", "NAVPERS_1070_613_TEMPLATE.pdf")
)
OUTDIR = os.environ.get("SEA_PAY_OUTPUT", os.path.join(ROOT, "OUTPUT"))

os.makedirs(OUTDIR, exist_ok=True)

# Font (Linux)
FONT_PATH = os.path.join(ROOT, "Times_New_Roman.ttf")
pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_PATH))
FONT_NAME = "TimesNewRoman"
FONT_SIZE = 10


def ocr_pdf(path):
    images = convert_from_path(path)
    out = ""
    for img in images:
        out += pytesseract.image_to_string(img)
    return out.upper()


def make_pdf(template_path, output_path, draw_func):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont(FONT_NAME, FONT_SIZE)

    # Custom drawing callback
    draw_func(c)

    c.save()
    buf.seek(0)

    overlay = PdfReader(buf)
    template = PdfReader(template_path)

    base = template.pages[0]
    base.merge_page(overlay.pages[0])

    writer = PdfWriter()
    writer.add_page(base)

    for i in range(1, len(template.pages)):
        writer.add_page(template.pages[i])

    with open(output_path, "wb") as f:
        writer.write(f)

    print("CREATED:", output_path)

