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

from .core.logger import (
    LIVE_LOGS,
    log,
    clear_logs,
    get_progress,
    reset_progress,
    set_progress,
)
from .core.config import (
    DATA_DIR,
    OUTPUT_DIR,
    TEMPLATE,
    RATE_FILE,
    PACKAGE_FOLDER,
    SUMMARY_TXT_FOLDER,
    SUMMARY_PDF_FOLDER,
    TORIS_CERT_FOLDER,
    REVIEW_JSON_PATH,   # <-- Phase 5 needs this
)
from .processing import process_all
import app.core.rates as rates

# Phase 5 (Option A): overrides are UI-only, no reprocess
from app.core.overrides import (
    save_override,
    clear_overrides,
    apply_overrides,
)

bp = Blueprint("routes", __name__)


# ---------------------------------------------------------
# EXISTING UI ROUTES (UNCHANGED)
# ---------------------------------------------------------

@bp.route("/", methods=["GET"])
def home():
    return render_template(
        "index.html",
        template_path=TEMPLATE,
        rate_path=RATE_FILE,
    )


@bp.route("/process", methods=["POST"])
def process_route():
    clear_logs()
    reset_progress()
    log("=== PROCESS STARTED ===")

    # Initialize progress so the UI sees 'processing'
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

    # Save uploaded TORIS PDFs
    files = request.files.getlist("files")
    for f in files:
        if f and f.filename:
            save_path = os.path.join(DATA_DIR, f.filename)
            f.save(save_path)
            log(f"SAVED INPUT FILE → {save_path}")

    # Save template
    template_file = request.files.get("template_file")
    if template_file and template_file.filename:
        # TEMPLATE is a full file path
        os.makedirs(os.path.dirname(TEMPLATE), exist_ok=True)
        template_file.save(TEMPLATE)
        log(f"UPDATED TEMPLATE → {TEMPLATE}")

    # Save CSV
    rate_file = request.files.get("rate_file")
    if rate_file and rate_file.filename:
        # RATE_FILE is a full file path
        os.makedirs(os.path.dirname(RATE_FILE), exist_ok=True)
        rate_file.save(RATE_FILE)
        log(f"UPDATED CSV FILE → {RATE_FILE}")

        # Reload CSV
        try:
            rates.load_rates(RATE_FILE)
            log("RATES RELOADED FROM CSV")
        except Exception as e:
            log(f"CSV RELOA D ERROR → {e}")

    strike_color = request.form.get("strike_color", "black")

    def _run():
        try:
            process_all(strike_color=strike_color)
            # Keep your existing "mark progress COMPLETE" behavior
            set_progress(
                status="complete",
                current_step="Processing complete",
                percentage=100,
            )
        except Exception as e:
            log(f"PROCESS ERROR → {e}")
            set_progress(status="error", current_step="Processing error")

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()

    return jsonify({"status": "STARTED"})


@bp.route("/logs")
def get_logs():
    return "\n".join(LIVE_LOGS)


@bp.route("/progress")
def progress_route():
    return jsonify(get_progress())


@bp.route("/stream")
def stream_logs():
    def event_stream():
        last_len = 0
        while True:
            current = "\n".join(LIVE_LOGS)
            if len(current) != last_len:
                last_len = len(current)
                yield f"data: {current}\n\n"
            time.sleep(1)

    return Response(event_stream(), mimetype="text/event-stream")


@bp.route("/download_merged")
def download_merged():
    # Prevent crash if PACKAGE_FOLDER does not exist
    if not os.path.exists(PACKAGE_FOLDER):
        return "No merged package found. Run processor first.", 404

    merged_files = [
        f
        for f in os.listdir(PACKAGE_FOLDER)
        if f.startswith("MERGED_") and f.endswith(".pdf")
    ]

    if not merged_files:
        return "No merged files found.", 404

    latest = max(
        merged_files,
        key=lambda f: os.path.getmtime(os.path.join(PACKAGE_FOLDER, f)),
    )

    return send_from_directory(
        PACKAGE_FOLDER,
        latest,
        as_attachment=True,
    )


@bp.route("/download_summary")
def download_summary():
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as z:
        # TXT
        if os.path.exists(SUMMARY_TXT_FOLDER):
            for root, _, files in os.walk(SUMMARY_TXT_FOLDER):
                for f in files:
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, SUMMARY_TXT_FOLDER)
                    z.write(full, f"SUMMARY_TXT/{arc}")

        # PDF
        if os.path.exists(SUMMARY_PDF_FOLDER):
            for root, _, files in os.walk(SUMMARY_PDF_FOLDER):
                for f in files:
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, SUMMARY_PDF_FOLDER)
                    z.write(full, f"SUMMARY_PDF/{arc}")

    mem_zip.seek(0)
    return send_file(
        mem_zip,
        as_attachment=True,
        download_name="SUMMARY_BUNDLE.zip",
    )


@bp.route("/download_marked_sheets")
def download_marked_sheets():
    mem_zip = io.BytesIO()

    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.exists(TORIS_CERT_FOLDER):
            for root, _, files in os.walk(TORIS_CERT_FOLDER):
                for f in files:
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, TORIS_CERT_FOLDER)
                    z.write(full, f"TORIS_MARKED/{arc}")

    mem_zip.seek(0)
    return send_file(
        mem_zip,
        as_attachment=True,
        download_name="TORIS_MARKED_SHEETS.zip",
    )


@bp.route("/download_tracking")
def download_tracking():
    tracker_folder = os.path.join(OUTPUT_DIR, "TRACKER")
    mem_zip = io.BytesIO()

    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.exists(tracker_folder):
            for root, _, files in os.walk(tracker_folder):
                for f in files:
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, tracker_folder)
                    z.write(full, f"TRACKER/{arc}")

    mem_zip.seek(0)
    return send_file(mem_zip, as_attachment=True, download_name="TRACKER.zip")


@bp.route("/download_all")
def download_all():
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(OUTPUT_DIR):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, OUTPUT_DIR)
                z.write(full, arc)

    mem_zip.seek(0)
    return send_file(mem_zip, as_attachment=True, download_name="ALL_OUTPUT.zip")


@bp.route("/reset", methods=["POST"])
def reset_all():
    # Wipe /data/
    for root, dirs, files in os.walk(DATA_DIR):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except Exception:
                pass
        for d in dirs:
            try:
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            except Exception:
                pass

    # Wipe /output/
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except Exception:
                pass
        for d in dirs:
            try:
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            except Exception:
                pass

    clear_logs()

    return jsonify(
        {
            "message": "Reset complete",
            "status": "reset",
        }
    )


# ---------------------------------------------------------
# PHASE 5 — API (Option A: UI-only overrides, no reprocess)
# ---------------------------------------------------------

def _load_review_state():
    """
    Load SEA_PAY_REVIEW.json safely. Returns {} if missing or unreadable.
    """
    if not os.path.exists(REVIEW_JSON_PATH):
        return {}
    try:
        with open(REVIEW_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"REVIEW JSON READ ERROR → {e}")
        return {}


def _write_review_state(state: dict):
    """
    Write SEA_PAY_REVIEW.json safely.
    """
    try:
        os.makedirs(os.path.dirname(REVIEW_JSON_PATH), exist_ok=True)
        with open(REVIEW_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        log(f"REVIEW JSON WRITE ERROR → {e}")
        raise


@bp.route("/api/members", methods=["GET"])
def api_members():
    """
    Returns list of member keys (e.g., 'STGC MYSLINSKI,SARAH').
    """
    state = _load_review_state()
    return jsonify(sorted(state.keys()))


@bp.route("/api/member/<path:member_key>/sheets", methods=["GET"])
def api_member_sheets(member_key):
    """
    Returns list of sheets for the member.
    """
    state = _load_review_state()
    member = state.get(member_key)
    if not member:
        return jsonify([])

    out = []
    for s in member.get("sheets", []):
        out.append(
            {
                "source_file": s.get("source_file"),
                "reporting_period": s.get("reporting_period", {}),
                "parse_confidence": s.get("parse_confidence"),
                "parsing_warnings": s.get("parsing_warnings", []),
                "stats": s.get("stats", {}),
                "total_valid_days": s.get("total_valid_days"),
            }
        )
    return jsonify(out)


@bp.route("/api/member/<path:member_key>/sheet/<path:sheet_file>", methods=["GET"])
def api_member_sheet(member_key, sheet_file):
    """
    Returns rows + invalid_events for a specific sheet.
    Adds stable indexes so UI can refer back when saving overrides.
    """
    state = _load_review_state()
    member = state.get(member_key)
    if not member:
        return jsonify({"error": "member not found"}), 404

    for s in member.get("sheets", []):
        if s.get("source_file") == sheet_file:
            rows = []
            for i, r in enumerate(s.get("rows", [])):
                rc = dict(r)
                rc["index"] = i
                rows.append(rc)

            invalids = []
            for i, e in enumerate(s.get("invalid_events", [])):
                ec = dict(e)
                ec["index"] = i
                invalids.append(ec)

            return jsonify(
                {
                    "member_key": member_key,
                    "sheet_file": sheet_file,
                    "reporting_period": s.get("reporting_period", {}),
                    "parse_confidence": s.get("parse_confidence"),
                    "parsing_warnings": s.get("parsing_warnings", []),
                    "stats": s.get("stats", {}),
                    "rows": rows,
                    "invalid_events": invalids,
                }
            )

    return jsonify({"error": "sheet not found"}), 404


@bp.route("/api/override", methods=["POST"])
def api_override_save():
    """
    Save an override (Option A: store in /app/data/overrides/*.json),
    then re-apply overrides into SEA_PAY_REVIEW.json WITHOUT reprocessing PDFs.
    """
    payload = request.get_json(silent=True) or {}

    member_key = payload.get("member_key")
    sheet_file = payload.get("sheet_file")
    event_index = payload.get("event_index")
    status = payload.get("status")  # "valid" or "invalid"
    reason = payload.get("reason", "")
    target = payload.get("target", "row")  # "row" or "invalid"

    if not member_key or not sheet_file:
        return jsonify({"error": "member_key and sheet_file required"}), 400
    if not isinstance(event_index, int):
        return jsonify({"error": "event_index must be an integer"}), 400
    if status not in ("valid", "invalid"):
        return jsonify({"error": "status must be 'valid' or 'invalid'"}), 400
    if target not in ("row", "invalid"):
        return jsonify({"error": "target must be 'row' or 'invalid'"}), 400

    # IMPORTANT: Our overrides engine uses a single event_index; to avoid ambiguity
    # we encode the target in the sheet_file string OR keep target separate.
    # We keep it separate in payload, but overrides.py (Phase 4) currently only keys
    # off sheet_file + event_index. So we map target into an adjusted index space:
    #
    # - For "row": event_index is row index
    # - For "invalid": event_index is invalid_events index BUT needs uniqueness
    #
    # SAFE approach: store invalid overrides as negative indexes.
    # This avoids collisions with rows.
    store_index = event_index if target == "row" else -(event_index + 1)

    try:
        save_override(
            member_key=member_key,
            sheet_file=sheet_file,
            event_index=store_index,
            status=status,
            reason=reason,
            source="manual",
        )
    except Exception as e:
        log(f"OVERRIDE SAVE ERROR → {e}")
        return jsonify({"error": "failed to save override"}), 500

    # Re-apply overrides into JSON (Option A behavior)
    state = _load_review_state()
    if member_key in state:
        try:
            state[member_key] = apply_overrides(member_key, state[member_key])
            _write_review_state(state)
        except Exception:
            return jsonify({"error": "failed to apply override"}), 500

    return jsonify({"status": "override_saved"})


@bp.route("/api/override", methods=["DELETE"])
def api_override_clear():
    """
    Clear all overrides for a member (delete their override file),
    then rewrite SEA_PAY_REVIEW.json back to base (still stored output).
    NOTE: This does NOT re-run processing; it only removes override overlay.
    """
    payload = request.get_json(silent=True) or {}
    member_key = payload.get("member_key")

    if not member_key:
        return jsonify({"error": "member_key required"}), 400

    try:
        clear_overrides(member_key)
    except Exception as e:
        log(f"OVERRIDE CLEAR ERROR → {e}")
        return jsonify({"error": "failed to clear overrides"}), 500

    # Reload + re-apply overrides for everyone (member cleared, so base stays)
    state = _load_review_state()
    if member_key in state:
        try:
            # apply_overrides will now do nothing for that member since file is gone
            state[member_key] = apply_overrides(member_key, state[member_key])
            _write_review_state(state)
        except Exception:
            return jsonify({"error": "failed to refresh json"}), 500

    return jsonify({"status": "overrides_cleared"})
