import os
import tempfile
import zipfile
from flask import Blueprint, render_template, request, send_from_directory, jsonify

# Correct imports (relative)
from .core.logger import LIVE_LOGS, log, clear_logs
from .core.config import (
    DATA_DIR,
    OUTPUT_DIR,
    TEMPLATE,
    RATE_FILE,
    SEA_PAY_PG13_FOLDER,
    TORIS_CERT_FOLDER,
    SUMMARY_TXT_FOLDER,
    SUMMARY_PDF_FOLDER,
    PACKAGE_FOLDER,
    TRACKER_FOLDER,
)
from .processing import process_all
import app.core.rates as rates  # keep as-is for correct loading

bp = Blueprint("main", __name__)


# ------------------------------------------------
# CLEANUP ALL INPUT + OUTPUT
# ------------------------------------------------
def cleanup_all_folders():
    deleted = 0
    for base in (DATA_DIR, OUTPUT_DIR):
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                    deleted += 1
                except Exception as e:
                    log(f"CLEANUP ERROR → {f}: {e}")
    return deleted


# ------------------------------------------------
# HOME PAGE
# ------------------------------------------------
@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":

        strike_color = request.form.get("strike_color", "black")

        # Upload PDF sheets
        for f in request.files.getlist("files"):
            if f.filename:
                f.save(os.path.join(DATA_DIR, f.filename))

        # Template override
        tpl = request.files.get("template_file")
        if tpl and tpl.filename:
            tpl.save(TEMPLATE)

        # Rates CSV upload
        csvf = request.files.get("rate_file")
        if csvf and csvf.filename:
            csvf.save(RATE_FILE)

            # Reload CSV mappings
            rates.RATES = rates.load_rates()
            rates.CSV_IDENTITIES.clear()

            for key, rate in rates.RATES.items():
                last, first = key.split(",", 1)

                def normalize_for_id(text):
                    import re
                    t = re.sub(r"\(.*?\)", "", text.upper())
                    t = re.sub(r"[^A-Z ]", "", t)
                    return " ".join(t.split())

                full_norm = normalize_for_id(f"{first} {last}")
                rates.CSV_IDENTITIES.append((full_norm, rate, last, first))

        # Run engine
        process_all(strike_color=strike_color)

    return render_template(
        "index.html",
        logs="\n".join(LIVE_LOGS),
        template_path=TEMPLATE,
        rate_path=RATE_FILE,
    )


# ------------------------------------------------
# LIVE LOGS
# ------------------------------------------------
@bp.route("/logs")
def get_logs():
    return "\n".join(LIVE_LOGS)


# ------------------------------------------------
# EXPORT ZIP – EVERYTHING IN OUTPUT FOLDER
# ------------------------------------------------
@bp.route("/download_all")
def download_all():
    zip_path = os.path.join(tempfile.gettempdir(), "SeaPay_Output.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(OUTPUT_DIR):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, OUTPUT_DIR)
                z.write(full, arcname=arc)

    return send_from_directory(
        os.path.dirname(zip_path),
        os.path.basename(zip_path),
        as_attachment=True,
        download_name="SeaPay_Output.zip",
    )


# ------------------------------------------------
# MERGED SEA PAY PG13 DOWNLOAD
# ------------------------------------------------
@bp.route("/download_merged")
def download_merged():
    fpath = os.path.join(PACKAGE_FOLDER, "MERGED_SEA_PAY_PG13.pdf")

    if not os.path.isfile(fpath):
        return "Merged PG13 file not found. Run processor first.", 404

    return send_from_directory(
        PACKAGE_FOLDER,
        "MERGED_SEA_PAY_PG13.pdf",
        as_attachment=True,
    )


# ------------------------------------------------
# MERGED SUMMARY DOWNLOAD
# ------------------------------------------------
@bp.route("/download_summary")
def download_summary():
    fpath = os.path.join(PACKAGE_FOLDER, "MERGED_SUMMARY.pdf")

    if not os.path.isfile(fpath):
        return "Merged Summary PDF not found. Run processor first.", 404

    return send_from_directory(
        PACKAGE_FOLDER,
        "MERGED_SUMMARY.pdf",
        as_attachment=True,
    )


# ------------------------------------------------
# TORIS SEA PAY CERT SHEETS DOWNLOAD
# ------------------------------------------------
@bp.route("/download_marked_sheets")
def download_marked_sheets():
    zip_path = os.path.join(tempfile.gettempdir(), "TORIS_Sea_Pay_Cert_Sheets.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in os.listdir(TORIS_CERT_FOLDER):
            full = os.path.join(TORIS_CERT_FOLDER, f)
            if os.path.isfile(full):
                z.write(full, arcname=f)

    return send_from_directory(
        os.path.dirname(zip_path),
        os.path.basename(zip_path),
        as_attachment=True,
        download_name="TORIS_Sea_Pay_Cert_Sheets.zip",
    )


# ------------------------------------------------
# VALIDATION LOGS DOWNLOAD
# ------------------------------------------------
@bp.route("/download_validation")
def download_validation():
    validation_dir = os.path.join(OUTPUT_DIR, "validation")

    zip_path = os.path.join(tempfile.gettempdir(), "Validation_Reports.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.isdir(validation_dir):
            for f in os.listdir(validation_dir):
                full = os.path.join(validation_dir, f)
                if os.path.isfile(full):
                    z.write(full, arcname=f)

    return send_from_directory(
        os.path.dirname(zip_path),
        os.path.basename(zip_path),
        as_attachment=True,
        download_name="Validation_Reports.zip",
    )


# ------------------------------------------------
# TRACKER DOWNLOAD
# ------------------------------------------------
@bp.route("/download_tracking")
def download_tracking():
    zip_path = os.path.join(tempfile.gettempdir(), "SeaPay_Tracking_Package.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:

        # Validation
        vdir = os.path.join(OUTPUT_DIR, "validation")
        if os.path.isdir(vdir):
            for f in os.listdir(vdir):
                full = os.path.join(vdir, f)
                if os.path.isfile(full):
                    z.write(full, arcname=f"validation/{f}")

        # Tracker JSON + CSV
        if os.path.isdir(TRACKER_FOLDER):
            for f in os.listdir(TRACKER_FOLDER):
                full = os.path.join(TRACKER_FOLDER, f)
                if os.path.isfile(full):
                    z.write(full, arcname=f"tracker/{f}")

    return send_from_directory(
        os.path.dirname(zip_path),
        os.path.basename(zip_path),
        as_attachment=True,
        download_name="SeaPay_Tracking_Package.zip",
    )


# ------------------------------------------------
# RESET SYSTEM
# ------------------------------------------------
@bp.route("/reset", methods=["POST"])
def reset():
    deleted = cleanup_all_folders()
    clear_logs()
    return jsonify({
        "status": "success",
        "message": f"Reset complete. {deleted} files deleted."
    })
