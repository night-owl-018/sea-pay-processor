import threading
import time
import os
import io
import zipfile
import shutil
import json

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    send_file,
    send_from_directory,
    Response,
)

from app.core.logger import (
    LIVE_LOGS,
    log,
    clear_logs,
    get_progress,
    reset_progress,
    set_progress,
)

from app.core.config import (
    DATA_DIR,
    OUTPUT_DIR,
    TEMPLATE,
    RATE_FILE,
    PACKAGE_FOLDER,
    REVIEW_JSON_PATH,
)

from app.processing import process_all
import app.core.rates as rates

from app.core.overrides import (
    save_override,
    clear_overrides,
    apply_overrides,
)

bp = Blueprint("routes", __name__)

# =========================================================
# UI ROUTES
# =========================================================

@bp.route("/", methods=["GET"])
def home():
    return render_template(
        "index.html",
        template_path=TEMPLATE,
        rate_path=RATE_FILE,
    )


# =========================================================
# PROCESS ROUTE
# =========================================================

@bp.route("/process", methods=["POST"])
def process_route():
    clear_logs()
    reset_progress()
    log("=== PROCESS STARTED ===")

    set_progress(
        status="processing",
        total_files=0,
        current_file=0,
        current_step="Preparing input files",
        percentage=0,
        details={
            "files_processed": 0,
            "valid_days": 0,
            "invalid_events": 0,
            "pg13_created": 0,
            "toris_marked": 0,
        },
    )

    # -------------------------------------------------
    # PATCH 1 — ACCEPT UI + BACKEND FIELD NAMES
    # -------------------------------------------------

    files = (
        request.files.getlist("files")
        or request.files.getlist("pdfs")
    )

    for f in files:
        if f and f.filename:
            save_path = os.path.join(DATA_DIR, f.filename)
            f.save(save_path)
            log(f"SAVED INPUT FILE → {save_path}")

    template_file = (
        request.files.get("template_file")
        or request.files.get("template_pdf")
    )
    if template_file and template_file.filename:
        os.makedirs(os.path.dirname(TEMPLATE), exist_ok=True)
        template_file.save(TEMPLATE)
        log(f"UPDATED TEMPLATE → {TEMPLATE}")

    rate_file = (
        request.files.get("rate_file")
        or request.files.get("rates_csv")
    )
    if rate_file and rate_file.filename:
        os.makedirs(os.path.dirname(RATE_FILE), exist_ok=True)
        rate_file.save(RATE_FILE)
        log(f"UPDATED CSV FILE → {RATE_FILE}")

        try:
            rates.load_rates()
            log("RATES RELOADED FROM CSV")
        except Exception as e:
            log(f"CSV RELOAD ERROR → {e}")

    strike_color = (
        request.form.get("strike_color")
        or request.form.get("strikeout_color")
        or "black"
    )

    # -------------------------------------------------

    def _run():
        try:
            process_all(strike_color=strike_color)
            set_progress(
                status="complete",
                current_step="Processing complete",
                percentage=100,
            )
        except Exception as e:
            log(f"PROCESS ERROR → {e}")
            set_progress(
                status="error",
                current_step="Processing error",
            )

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "STARTED"})


# =========================================================
# PROGRESS & LOG STREAM
# =========================================================

@bp.route("/progress")
def progress_route():
    return jsonify(get_progress())


@bp.route("/stream")
def stream_logs():
    def event_stream():
        yield "data: [CONNECTED]\n\n"
        last_len = 0
        while True:
            current_len = len(LIVE_LOGS)
            if current_len > last_len:
                for i in range(last_len, current_len):
                    yield f"data: {LIVE_LOGS[i]}\n\n"
                last_len = current_len
            time.sleep(0.5)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# =========================================================
# REVIEW / OVERRIDE API
# =========================================================

def _load_review_state():
    if not os.path.exists(REVIEW_JSON_PATH):
        return {}
    try:
        with open(REVIEW_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"REVIEW JSON READ ERROR → {e}")
        return {}


@bp.route("/api/members")
def api_members():
    return jsonify(sorted(_load_review_state().keys()))


@bp.route("/api/member/<path:member_key>/sheets")
def api_member_sheets(member_key):
    state = _load_review_state()
    member = state.get(member_key)
    if not member:
        return jsonify([])

    out = []
    for s in member.get("sheets", []):
        out.append({
            "sheet_id": s.get("source_file"),
            "valid_rows": s.get("rows", []),
            "invalid_rows": s.get("invalid_events", []),
        })

    return jsonify(out)


# =========================================================
# PATCH 2 — SINGLE SHEET REVIEW ENDPOINT
# =========================================================

@bp.route("/api/member/<path:member_key>/sheet/<path:sheet_id>")
def api_member_single_sheet(member_key, sheet_id):
    state = _load_review_state()
    member = state.get(member_key)
    if not member:
        return jsonify({}), 404

    for sheet in member.get("sheets", []):
        if sheet.get("source_file") == sheet_id:
            return jsonify({
                "sheet_id": sheet_id,
                "reporting_period": sheet.get("reporting_period"),
                "stats": sheet.get("stats"),
                "valid_rows": sheet.get("rows", []),
                "invalid_rows": sheet.get("invalid_events", []),
                "parsing_warnings": sheet.get("parsing_warnings", []),
                "parse_confidence": sheet.get("parse_confidence"),
            })

    return jsonify({}), 404


@bp.route("/api/override", methods=["POST"])
def api_override_save():
    payload = request.get_json(silent=True) or {}

    save_override(**payload)

    state = _load_review_state()
    state[payload["member_key"]] = apply_overrides(
        payload["member_key"],
        state[payload["member_key"]],
    )

    os.makedirs(os.path.dirname(REVIEW_JSON_PATH), exist_ok=True)
    with open(REVIEW_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)

    return jsonify({"status": "override_saved"})


@bp.route("/api/override", methods=["DELETE"])
def api_override_clear():
    payload = request.get_json(silent=True) or {}
    clear_overrides(payload["member_key"])
    return jsonify({"status": "overrides_cleared"})


# =========================================================
# DOWNLOAD & RESET ROUTES
# =========================================================

@bp.route("/download_all")
def download_all():
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(OUTPUT_DIR):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, OUTPUT_DIR))
    mem_zip.seek(0)
    return send_file(mem_zip, as_attachment=True, download_name="ALL_OUTPUT.zip")


@bp.route("/reset", methods=["POST"])
def reset_all():
    for root, dirs, files in os.walk(DATA_DIR):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except Exception:
                pass
        for d in dirs:
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)

    for root, dirs, files in os.walk(OUTPUT_DIR):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except Exception:
                pass
        for d in dirs:
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)

    clear_logs()
    return jsonify({"status": "reset"})
