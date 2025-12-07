import os
import io
import zipfile
import shutil

from flask import (
    Blueprint, render_template, request,
    jsonify, send_file, send_from_directory
)

from .core.logger import LIVE_LOGS, log, clear_logs
from .core.config import (
    DATA_DIR,
    OUTPUT_DIR,
    TEMPLATE,
    RATE_FILE,
    PACKAGE_FOLDER,
    SUMMARY_TXT_FOLDER,
    SUMMARY_PDF_FOLDER,
    TORIS_CERT_FOLDER,
)
from .processing import process_all
import app.core.rates as rates


bp = Blueprint("routes", __name__)


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
    log("=== PROCESS STARTED ===")

    # Save uploaded TORIS PDFs
    files = request.files.getlist("files")
    for f in files:
        if f.filename:
            save_path = os.path.join(DATA_DIR, f.filename)
            f.save(save_path)
            log(f"SAVED INPUT FILE → {save_path}")

    # Save template
    template_file = request.files.get("template_file")
    if template_file and template_file.filename:
        template_file.save(TEMPLATE)
        log(f"UPDATED TEMPLATE → {TEMPLATE}")

    # Save CSV
    rate_file = request.files.get("rate_file")
    if rate_file and rate_file.filename:
        rate_file.save(RATE_FILE)
        log(f"UPDATED CSV FILE → {RATE_FILE}")

        # Reload CSV (patched)
        try:
            rates.load_csv_file(RATE_FILE)
        except Exception as e:
            log(f"CSV RELOAD ERROR → {e}")

    strike_color = request.form.get("strike_color", "black")

    process_all(strike_color=strike_color)

    log("=== PROCESS COMPLETE ===")

    return jsonify({"status": "OK"})


@bp.route("/logs")
def get_logs():
    return "\n".join(LIVE_LOGS)


@bp.route("/download_merged")
def download_merged():
    merged_files = [
        f for f in os.listdir(PACKAGE_FOLDER)
        if f.startswith("MERGED_") and f.endswith(".pdf")
    ]

    if not merged_files:
        return "No merged files found.", 404

    latest = max(
        merged_files,
        key=lambda f: os.path.getmtime(os.path.join(PACKAGE_FOLDER, f))
    )

    return send_from_directory(
        PACKAGE_FOLDER,
        latest,
        as_attachment=True
    )


@bp.route("/download_summary")
def download_summary():
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as z:

        # TXT summaries
        for root, _, files in os.walk(SUMMARY_TXT_FOLDER):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, SUMMARY_TXT_FOLDER)
                z.write(full, f"SUMMARY_TXT/{arc}")

        # PDF summaries
        for root, _, files in os.walk(SUMMARY_PDF_FOLDER):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, SUMMARY_PDF_FOLDER)
                z.write(full, f"SUMMARY_PDF/{arc}")

    mem_zip.seek(0)
    return send_file(mem_zip, as_attachment=True, download_name="SUMMARY_EXPORT.zip")


@bp.route("/download_marked_sheets")
def download_marked_sheets():
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as z:

        for root, _, files in os.walk(TORIS_CERT_FOLDER):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, TORIS_CERT_FOLDER)
                z.write(full, f"TORIS_SEA_PAY_CERT_SHEET/{arc}")

    mem_zip.seek(0)
    return send_file(mem_zip, as_attachment=True, download_name="TORIS_MARKED_SHEETS.zip")


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
    return send_file(mem_zip, as_attachment=True, download_name="SEA_PAY_EXPORT_ALL.zip")


@bp.route("/reset", methods=["POST"])
def reset_all():
    """Reset input/output folders and logs."""

    # Clean input folder
    for root, _, files in os.walk(DATA_DIR):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except Exception:
                pass

    # Clean output folder
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

    # PATCH: UI expects "message"
    return jsonify({
        "message": "Reset complete",
        "status": "reset"
    })
