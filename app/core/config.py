import os
import json
from pathlib import Path

from app.core.io_utils import atomic_write_json

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent

def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value

def _resolve_dir(name: str, local_name: str | None = None) -> str:
    env_key = f"SEA_PAY_{name.upper()}_DIR"
    env_override = os.environ.get(env_key)
    if env_override:
        return env_override
    mounted = Path("/app") / name
    local = PROJECT_ROOT / (local_name or name)
    return str(mounted if Path("/app").exists() else local)

TEMPLATE_DIR = _resolve_dir("pdf_template")
CONFIG_DIR = _resolve_dir("config")
DATA_DIR = _resolve_dir("data")
OUTPUT_DIR = _resolve_dir("output")

TEMPLATE = os.path.join(TEMPLATE_DIR, "NAVPERS_1070_613_TEMPLATE.pdf")
RATE_FILE = os.path.join(CONFIG_DIR, "atgsd_n811.csv")
SHIP_FILE = (
    os.path.join(CONFIG_DIR, "ships.txt")
    if os.path.exists(os.path.join(CONFIG_DIR, "ships.txt"))
    else str(PROJECT_ROOT / "ships.txt")
)
FONT_FILE = os.environ.get("SEA_PAY_FONT_FILE") or str(PROJECT_ROOT / "Times_New_Roman.ttf")

CERTIFYING_OFFICER_FILE = os.path.join(OUTPUT_DIR, "certifying_officer.json")
SIGNATURES_FILE = os.path.join(OUTPUT_DIR, "signatures.json")

PACKAGE_FOLDER = os.path.join(OUTPUT_DIR, "PACKAGE")
SUMMARY_TXT_FOLDER = os.path.join(OUTPUT_DIR, "SUMMARY_TXT")
SUMMARY_PDF_FOLDER = os.path.join(OUTPUT_DIR, "SUMMARY_PDF")
TORIS_CERT_FOLDER = os.path.join(OUTPUT_DIR, "TORIS_CERT")
SEA_PAY_PG13_FOLDER = os.path.join(OUTPUT_DIR, "SEA_PAY_PG13")
TRACKER_FOLDER = os.path.join(OUTPUT_DIR, "TRACKER")
PARSED_DIR = os.path.join(OUTPUT_DIR, "parsed")
OVERRIDES_DIR = os.path.join(OUTPUT_DIR, "overrides")
REPORTS_DIR = os.path.join(OUTPUT_DIR, "reports")
PREVIEWS_DIR = os.path.join(OUTPUT_DIR, "previews")
REVIEW_JSON_PATH = os.path.join(OUTPUT_DIR, "SEA_PAY_REVIEW.json")

FONT_NAME = "TimesNewRoman"
FONT_SIZE = 11

MAX_UPLOAD_MB = _env_int("SEA_PAY_MAX_UPLOAD_MB", 50, minimum=1, maximum=500)
LOG_PATH = os.environ.get("SEA_PAY_LOG_PATH", os.path.join(OUTPUT_DIR, "sea-pay.log"))
MASK_LOG_PATHS = _env_bool("SEA_PAY_MASK_LOG_PATHS", True)
ENABLE_PROXY_FIX = _env_bool("SEA_PAY_ENABLE_PROXY_FIX", True)
GUNICORN_WORKERS = _env_int("SEA_PAY_GUNICORN_WORKERS", 2, minimum=1, maximum=16)
GUNICORN_THREADS = _env_int("SEA_PAY_GUNICORN_THREADS", 4, minimum=1, maximum=32)
GUNICORN_TIMEOUT = _env_int("SEA_PAY_GUNICORN_TIMEOUT", 300, minimum=30, maximum=3600)

def ensure_runtime_dirs() -> None:
    for path in [
        TEMPLATE_DIR,
        CONFIG_DIR,
        DATA_DIR,
        OUTPUT_DIR,
        PACKAGE_FOLDER,
        SUMMARY_TXT_FOLDER,
        SUMMARY_PDF_FOLDER,
        TORIS_CERT_FOLDER,
        SEA_PAY_PG13_FOLDER,
        TRACKER_FOLDER,
        PARSED_DIR,
        OVERRIDES_DIR,
        REPORTS_DIR,
        PREVIEWS_DIR,
    ]:
        os.makedirs(path, exist_ok=True)

def load_certifying_officer():
    if not os.path.exists(CERTIFYING_OFFICER_FILE):
        return {}
    try:
        with open(CERTIFYING_OFFICER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {
                'rate': data.get('rate', '').strip(),
                'last_name': data.get('last_name', '').strip(),
                'first_name': data.get('first_name', '').strip(),
                'middle_name': data.get('middle_name', '').strip(),
                'date_yyyymmdd': data.get('date_yyyymmdd', '').strip(),
            }
    except Exception:
        return {}

def save_certifying_officer(rate, last_name, first_name, middle_name, date_yyyymmdd=""):
    atomic_write_json(CERTIFYING_OFFICER_FILE, {
        'rate': (rate or '').strip(),
        'last_name': (last_name or '').strip(),
        'first_name': (first_name or '').strip(),
        'middle_name': (middle_name or '').strip(),
        'date_yyyymmdd': (date_yyyymmdd or '').strip(),
    }, indent=2)

def get_certifying_officer_name():
    officer = load_certifying_officer()
    if not officer:
        return ""
    parts = [officer.get("rate", ""), officer.get("last_name", ""), officer.get("first_name", "")]
    return " ".join([p for p in parts if p]).strip()

def get_certifying_officer_name_pg13():
    officer = load_certifying_officer()
    if not officer:
        return ""
    rate = officer.get("rate", "")
    last_name = officer.get("last_name", "")
    first_name = officer.get("first_name", "")
    middle_name = officer.get("middle_name", "")
    if middle_name:
        return f"{rate} {first_name} {middle_name} {last_name}".strip()
    return f"{rate} {first_name} {last_name}".strip()

def get_certifying_date_yyyymmdd():
    officer = load_certifying_officer()
    return officer.get("date_yyyymmdd", "") if officer else ""

def get_signature_for_member_location(member_key):
    if not os.path.exists(SIGNATURES_FILE):
        return None
    try:
        with open(SIGNATURES_FILE, 'r', encoding='utf-8') as f:
            signatures = json.load(f)
        return signatures.get(member_key)
    except Exception:
        return None
