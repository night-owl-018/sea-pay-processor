import os
import sqlite3
import csv
from datetime import datetime
from pathlib import Path

# ----------------------------------------------------
# DB LOCATION
# ----------------------------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))

# Default to /config/seapay.db (for Docker),
# but fall back to local file for dev/testing.
DB_PATH = os.environ.get("SEA_PAY_DB", os.path.join(ROOT, "seapay.db"))

# Existing files (for initial seeding)
SHIP_FILE = os.path.join(ROOT, "ships.txt")
RATE_FILE = os.path.join(ROOT, "atgsd_n811.csv")


# ----------------------------------------------------
# BASIC CONNECTION HELPERS
# ----------------------------------------------------

def get_conn():
    """Return a SQLite connection with sane defaults."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ----------------------------------------------------
# SCHEMA CREATION
# ----------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS ships (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    normalized  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS names (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    last        TEXT NOT NULL,
    first       TEXT NOT NULL,
    rate        TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    UNIQUE(last, first)
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    input_path  TEXT,
    output_path TEXT,
    template    TEXT,
    status      TEXT,
    notes       TEXT,
    exit_code   INTEGER
);

CREATE TABLE IF NOT EXISTS hashes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256      TEXT NOT NULL UNIQUE,
    filename    TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    run_id      INTEGER,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS templates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    filename     TEXT NOT NULL,
    version_label TEXT,
    upload_time  TEXT NOT NULL,
    last_used    TEXT,
    active       INTEGER NOT NULL DEFAULT 1
);
"""


def init_db():
    """Create tables if they do not exist."""
    Path(os.path.dirname(DB_PATH) or ".").mkdir(parents=True, exist_ok=True)

    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------
# NORMALIZATION HELPERS (MATCH EXISTING PYTHON LOGIC)
# ----------------------------------------------------

import re
from difflib import get_close_matches


def normalize(text: str) -> str:
    """Mirror the normalize() function in your current code."""
    text = re.sub(r"\\(.*?\\)", "", text or "")
    text = re.sub(r"[^A-Z ]", "", text.upper())
    return " ".join(text.split())


# ----------------------------------------------------
# SEEDING FROM EXISTING FILES
# ----------------------------------------------------

def _clean_header(h: str) -> str:
    if h is None:
        return ""
    return h.lstrip("\\ufeff").strip().strip('"').lower()


def seed_ships_from_txt():
    """Initial one-time import from ships.txt into ships table."""
    if not os.path.exists(SHIP_FILE):
        print("⚠ seed_ships_from_txt: ships.txt not found, skipping.")
        return

    conn = get_conn()
    cur = conn.cursor()

    # Check if ships table already has data
    cur.execute("SELECT COUNT(*) AS c FROM ships;")
    count = cur.fetchone()["c"]
    if count > 0:
        print(f"✅ ships table already has {count} rows, skipping seed.")
        conn.close()
        return

    created_at = now_iso()

    with open(SHIP_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    rows = []
    for name in lines:
        norm = normalize(name)
        if not norm:
            continue
        rows.append((name.upper(), norm, 1, created_at))

    cur.executemany(
        "INSERT OR IGNORE INTO ships (name, normalized, active, created_at) VALUES (?, ?, ?, ?);",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"✅ Seeded {len(rows)} ships into DB.")


def seed_names_from_csv():
    """Initial one-time import from atgsd_n811.csv into names table."""
    if not os.path.exists(RATE_FILE):
        print("⚠ seed_names_from_csv: atgsd_n811.csv not found, skipping.")
        return

    conn = get_conn()
    cur = conn.cursor()

    # Check if names table already has data
    cur.execute("SELECT COUNT(*) AS c FROM names;")
    count = cur.fetchone()["c"]
    if count > 0:
        print(f"✅ names table already has {count} rows, skipping seed.")
        conn.close()
        return

    created_at = now_iso()
    rows = []

    with open(RATE_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            print("⚠ names CSV has no headers, skipping seed.")
            conn.close()
            return

        reader.fieldnames = [_clean_header(h) for h in reader.fieldnames]

        for raw_row in reader:
            row = {}
            for k, v in raw_row.items():
                key = _clean_header(k)
                if not key:
                    continue
                row[key] = (v or "").replace("\\t", "").strip()

            last = (row.get("last") or "").upper()
            first = (row.get("first") or "").upper()
            rate = (row.get("rate") or "").upper()

            if not last or not rate:
                continue

            rows.append((last, first, rate, 1, created_at))

    if rows:
        cur.executemany(
            "INSERT OR IGNORE INTO names (last, first, rate, active, created_at) "
            "VALUES (?, ?, ?, ?, ?);",
            rows,
        )
        conn.commit()
        print(f"✅ Seeded {len(rows)} names into DB.")
    else:
        print("⚠ No valid name rows found in CSV.")

    conn.close()


def initialize_and_seed():
    """Call this once at startup (e.g., from main or backend)."""
    print(f"📦 Using DB at: {DB_PATH}")
    init_db()
    seed_ships_from_txt()
    seed_names_from_csv()
    print("✅ Database initialization and seeding complete.")
