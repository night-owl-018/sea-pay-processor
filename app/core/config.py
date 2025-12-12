import os

# -----------------------------------
# Base paths
# -----------------------------------

# This file lives in app/core/, so:
# BASE_DIR      = app/core
# PROJECT_ROOT  = repo root (ATGSD-SEA-PAY-PROCESSOR)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))

# -----------------------------------
# Existing temp/output locations
# (KEPT EXACTLY AS BEFORE)
# -----------------------------------

TEMP_DIR = os.path.join(PROJECT_ROOT, "temp")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

PDF_TEMPLATE = os.path.join(
    PROJECT_ROOT,
    "pdf_template",
    "NAVPERS_1070_613_TEMPLATE.pdf",
)

RATE_FILE = os.path.join(PROJECT_ROOT, "config", "atgsd_n811.csv")
LOGGER_NAME = "sea_pay_logger"

# Ensure existing directories still exist
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# -----------------------------------
# NEW: Data directories for the
# upgraded Sea Pay Processor
# -----------------------------------

# Root data directory for all structured outputs
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# Parsed JSON per sheet owner
PARSED_DIR = os.path.join(DATA_DIR, "parsed")

# Manual overrides per sheet owner
OVERRIDES_DIR = os.path.join(DATA_DIR, "overrides")

# Validation reports (per member or global)
REPORTS_DIR = os.path.join(DATA_DIR, "reports")

# Preview artifacts (PG-13 text, 1070/613 text or PDFs)
PREVIEWS_DIR = os.path.join(DATA_DIR, "previews")

# Ensure new data directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PARSED_DIR, exist_ok=True)
os.makedirs(OVERRIDES_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(PREVIEWS_DIR, exist_ok=True)
