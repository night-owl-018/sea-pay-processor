import os
import json
import base64
import hashlib
import threading
from io import BytesIO
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


def _env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return str(value).strip() if value is not None else default.strip()


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
APP_VERSION = _env_str("SEA_PAY_APP_VERSION", "1.1.0")
MAX_SIGNATURE_IMAGE_MB = _env_int("SEA_PAY_MAX_SIGNATURE_IMAGE_MB", 5, minimum=1, maximum=25)
SIGNATURE_STORE_LOCK = threading.RLock()

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



def _default_signature_store() -> dict:
    return {
        "signatures": [],
        "assignments_by_member": {},
        "assignment_rules": {
            "allowed_locations": [
                "toris_certifying_officer",
                "pg13_certifying_official",
                "pg13_verifying_official",
            ]
        },
    }



def _normalize_signature_store(data: dict | None = None) -> dict:
    merged = _default_signature_store()
    if isinstance(data, dict):
        merged.update({k: v for k, v in data.items() if v is not None})

    normalized_signatures = []
    for raw in merged.get("signatures", []) or []:
        if not isinstance(raw, dict):
            continue
        entry = {
            "id": str(raw.get("id") or "").strip(),
            "name": str(raw.get("name") or "").strip(),
            "role": str(raw.get("role") or "").strip(),
            "image_base64": str(raw.get("image_base64") or "").strip(),
            "thumbnail_base64": str(raw.get("thumbnail_base64") or "").strip(),
            "created": str(raw.get("created") or "").strip(),
            "device_id": str(raw.get("device_id") or "").strip(),
            "device_name": str(raw.get("device_name") or "").strip(),
            "metadata": raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {},
        }
        if entry["id"]:
            normalized_signatures.append(entry)
    merged["signatures"] = normalized_signatures

    assignments = merged.get("assignments_by_member", {})
    merged["assignments_by_member"] = assignments if isinstance(assignments, dict) else {}

    rules = merged.get("assignment_rules", {})
    if not isinstance(rules, dict):
        rules = {}
    merged["assignment_rules"] = {
        **_default_signature_store()["assignment_rules"],
        **rules,
    }
    return merged


def _decode_signature_image(sig_b64: str) -> bytes:
    sig_b64 = (sig_b64 or "").strip()
    if not sig_b64:
        raise ValueError("Signature image is required")
    try:
        raw = base64.b64decode(sig_b64, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 encoding") from exc
    if not raw:
        raise ValueError("Signature image is empty")
    max_bytes = MAX_SIGNATURE_IMAGE_MB * 1024 * 1024
    if len(raw) > max_bytes:
        raise ValueError(f"Signature image exceeds {MAX_SIGNATURE_IMAGE_MB} MB")
    return raw


def _validate_signature_image(sig_b64: str) -> tuple[bytes, str, tuple[int, int]]:
    from PIL import Image

    raw = _decode_signature_image(sig_b64)
    try:
        with Image.open(BytesIO(raw)) as img:
            image_format = (img.format or "").upper()
            size = img.size
            if image_format not in {"PNG", "JPEG", "JPG"}:
                raise ValueError("Signature image must be PNG or JPEG")
            if size[0] < 1 or size[1] < 1:
                raise ValueError("Signature image dimensions are invalid")
            if size[0] > 6000 or size[1] > 6000:
                raise ValueError("Signature image dimensions are too large")
            try:
                img.verify()
            except Exception:
                # Some very small PNGs trigger Pillow verify/load quirks; format+size are
                # enough for this service because downstream code only stores the bytes.
                pass
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Signature image is not a valid PNG or JPEG") from exc
    return raw, image_format, size


def validate_signature_payload(sig_b64: str) -> dict:
    raw, image_format, size = _validate_signature_image(sig_b64)
    return {
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "format": image_format,
        "width": size[0],
        "height": size[1],
    }


def _find_signature_by_hash(data: dict, sha256_hex: str) -> dict | None:
    for sig in data.get("signatures", []) or []:
        metadata = sig.get("metadata", {}) or {}
        if metadata.get("sha256") == sha256_hex:
            return sig
    return None


def load_signatures() -> dict:
    with SIGNATURE_STORE_LOCK:
        if not os.path.exists(SIGNATURES_FILE):
            return _default_signature_store()
        try:
            with open(SIGNATURES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            return _default_signature_store()
        return _normalize_signature_store(data)


def save_signatures(data: dict) -> None:
    with SIGNATURE_STORE_LOCK:
        atomic_write_json(SIGNATURES_FILE, _normalize_signature_store(data), indent=2)


def _signature_thumbnail_base64(image_b64: str, size: tuple[int, int] = (240, 80)) -> str:
    try:
        import base64
        from io import BytesIO
        from PIL import Image

        raw = base64.b64decode(image_b64)
        with Image.open(BytesIO(raw)) as img:
            img = img.convert("RGBA")
            img.thumbnail(size)
            buf = BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def save_signature(name, role, sig_b64, device_id="unknown", device_name="Unknown Device"):
    import uuid
    from datetime import datetime, UTC

    sig_b64 = (sig_b64 or "").strip()
    name = (name or "").strip()
    if not name or not sig_b64:
        return None

    metadata = validate_signature_payload(sig_b64)

    with SIGNATURE_STORE_LOCK:
        data = load_signatures()
        existing = _find_signature_by_hash(data, metadata["sha256"])
        if existing:
            existing["name"] = name
            existing["role"] = (role or "").strip()
            existing["device_id"] = (device_id or "unknown").strip()
            existing["device_name"] = (device_name or "Unknown Device").strip()
            existing["metadata"] = {**(existing.get("metadata") or {}), **metadata}
            if not existing.get("thumbnail_base64"):
                existing["thumbnail_base64"] = _signature_thumbnail_base64(sig_b64)
            save_signatures(data)
            return existing["id"]

        signature_id = f"sig_{uuid.uuid4().hex[:12]}"
        entry = {
            "id": signature_id,
            "name": name,
            "role": (role or "").strip(),
            "image_base64": sig_b64,
            "thumbnail_base64": _signature_thumbnail_base64(sig_b64),
            "created": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "device_id": (device_id or "unknown").strip(),
            "device_name": (device_name or "Unknown Device").strip(),
            "metadata": metadata,
        }
        data["signatures"].append(entry)
        save_signatures(data)
        return signature_id


def get_all_signatures(include_thumbnails: bool = False, include_full_res: bool = False) -> list[dict]:
    data = load_signatures()
    items = []
    for sig in data.get("signatures", []):
        item = {
            "id": sig.get("id"),
            "name": sig.get("name", ""),
            "role": sig.get("role", ""),
            "created": sig.get("created", ""),
            "device_id": sig.get("device_id", ""),
            "device_name": sig.get("device_name", ""),
            "metadata": sig.get("metadata", {}) or {},
        }
        if include_thumbnails:
            item["thumbnail_base64"] = sig.get("thumbnail_base64", "")
        if include_full_res:
            item["image_base64"] = sig.get("image_base64", "")
        items.append(item)
    return items


def delete_signature(signature_id: str) -> bool:
    data = load_signatures()
    before = len(data.get("signatures", []))
    data["signatures"] = [s for s in data.get("signatures", []) if s.get("id") != signature_id]
    if len(data["signatures"]) == before:
        return False

    for member_key, assignments in list((data.get("assignments_by_member") or {}).items()):
        if not isinstance(assignments, dict):
            continue
        for location, assigned_sig in list(assignments.items()):
            if assigned_sig == signature_id:
                assignments[location] = None
        data["assignments_by_member"][member_key] = assignments

    save_signatures(data)
    return True


def assign_signature(member_key: str, location: str, signature_id: str | None):
    member_key = (member_key or "").strip()
    location = (location or "").strip()
    allowed = set(load_signatures().get("assignment_rules", {}).get("allowed_locations", []))

    if not member_key:
        return False, "member_key is required"
    if location not in allowed:
        return False, "Invalid location"

    data = load_signatures()
    known_ids = {s.get("id") for s in data.get("signatures", [])}
    if signature_id is not None and signature_id not in known_ids:
        return False, "Signature not found"

    member_assignments = data.setdefault("assignments_by_member", {}).setdefault(member_key, {})
    member_assignments.setdefault("toris_certifying_officer", None)
    member_assignments.setdefault("pg13_certifying_official", None)
    member_assignments.setdefault("pg13_verifying_official", None)
    member_assignments[location] = signature_id
    save_signatures(data)
    return True, "Signature assignment updated"


def get_assignment_status(member_key: str | None = None) -> dict:
    data = load_signatures()
    assignments_by_member = data.get("assignments_by_member", {}) or {}
    allowed = data.get("assignment_rules", {}).get("allowed_locations", [])

    def summarize(assignments: dict) -> dict:
        return {
            "total_locations": len(allowed),
            "assigned_locations": sum(1 for loc in allowed if assignments.get(loc)),
            "missing_locations": [loc for loc in allowed if not assignments.get(loc)],
            "complete": all(assignments.get(loc) for loc in allowed),
        }

    if member_key:
        assignments = assignments_by_member.get(member_key, {}) or {}
        return summarize(assignments)

    by_member = {mk: summarize(assignments or {}) for mk, assignments in assignments_by_member.items()}
    complete_count = sum(1 for v in by_member.values() if v["complete"])
    return {
        "members": by_member,
        "member_count": len(by_member),
        "complete_count": complete_count,
        "incomplete_count": len(by_member) - complete_count,
    }


def auto_assign_signatures(member_key: str):
    data = load_signatures()
    signatures = data.get("signatures", [])
    if len(signatures) < 3:
        return False, "At least 3 signatures are required for auto-assign", 0

    ordered_ids = [sig.get("id") for sig in signatures[:3]]
    assignments = {
        "toris_certifying_officer": ordered_ids[0],
        "pg13_certifying_official": ordered_ids[1],
        "pg13_verifying_official": ordered_ids[2],
    }
    data.setdefault("assignments_by_member", {})[member_key] = assignments
    save_signatures(data)
    return True, "Auto-assigned 3 signatures", 3


def get_signature_for_member_location(member_key: str, location: str):
    data = load_signatures()
    assignments = (data.get("assignments_by_member", {}) or {}).get((member_key or "").strip(), {}) or {}
    signature_id = assignments.get((location or "").strip())
    if not signature_id:
        return None
    for sig in data.get("signatures", []):
        if sig.get("id") == signature_id:
            return sig.get("image_base64")
    return None
