import csv
import os
import re
import threading
from difflib import SequenceMatcher

from app.core.config import RATE_FILE
from app.core.logger import log
from app.core.ships import normalize


_RATES_LOCK = threading.Lock()
RATES = {}
CSV_IDENTITIES = []


def _clean_header(h):
    return h.lstrip("\ufeff").strip().strip('"').lower() if h else ""


def _normalize_for_id(text):
    t = re.sub(r"\(.*?\)", "", text.upper())
    t = re.sub(r"[^A-Z ]", "", t)
    return " ".join(t.split())


def _build_identities(rates):
    identities = []
    for key, rate in rates.items():
        last, first = key.split(",", 1)
        full_norm = _normalize_for_id(f"{first} {last}")
        identities.append((full_norm, rate, last, first))
    return identities


def load_rates():
    rates = {}
    if not os.path.exists(RATE_FILE):
        log("RATE FILE MISSING")
        return rates

    with open(RATE_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [_clean_header(h) for h in (reader.fieldnames or [])]

        for row in reader:
            last = (row.get("last") or "").upper().strip()
            first = (row.get("first") or "").upper().strip()
            rate = (row.get("rate") or "").upper().strip()
            if last and rate:
                rates[f"{last},{first}"] = rate

    log(f"RATES LOADED: {len(rates)}")
    return rates


def reload_rates():
    global RATES, CSV_IDENTITIES
    with _RATES_LOCK:
        RATES = load_rates()
        CSV_IDENTITIES = _build_identities(RATES)
        return RATES


reload_rates()


def lookup_csv_identity(name):
    ocr_norm = normalize(name)
    with _RATES_LOCK:
        identities = list(CSV_IDENTITIES)

    best = None
    best_score = 0.0

    for csv_norm, rate, last, first in identities:
        score = SequenceMatcher(None, ocr_norm, csv_norm).ratio()
        if score > best_score:
            best_score = score
            best = (rate, last, first)

    if best and best_score >= 0.60:
        rate, last, first = best
        log(f"CSV MATCH ({best_score:.2f}) → {rate} {last},{first}")
        return best

    log(f"CSV NO GOOD MATCH (best={best_score:.2f}) for [{name}]")
    return None


def get_rate(name):
    parts = normalize(name).split()
    if len(parts) < 2:
        return ""
    key = f"{parts[-1]},{parts[0]}"
    with _RATES_LOCK:
        return RATES.get(key, "")


def resolve_identity(name):
    csv_id = lookup_csv_identity(name)
    if csv_id:
        rate, last, first = csv_id
    else:
        parts = name.split()
        last = parts[-1] if parts else ""
        first = " ".join(parts[:-1]) if len(parts) > 1 else ""
        rate = get_rate(name)
    return rate, last, first
