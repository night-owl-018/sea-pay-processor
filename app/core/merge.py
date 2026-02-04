import os
import re
from PyPDF2 import PdfWriter, PdfReader
from app.core.logger import log
from app.core.config import (
    SEA_PAY_PG13_FOLDER,
    TORIS_CERT_FOLDER,
    SUMMARY_PDF_FOLDER,
    PACKAGE_FOLDER,
)

def _get_file_prefixes_from_folder(folder):
    """
    Scans a folder and extracts a sorted list of unique filename prefixes.
    Example: 'STG1_NIVERA_RYAN_N_SUMMARY.pdf' -> 'STG1_NIVERA_RYAN_N'
    """
    if not os.path.exists(folder):
        return []

    prefixes = set()
    files = [f for f in os.listdir(folder) if f.lower().endswith(".pdf")]

    for f in files:
        if f.endswith("_SUMMARY.pdf"):
            prefixes.add(f[:-12])

    return sorted(list(prefixes))

def _create_bookmark_name(safe_prefix):
    """
    Converts a filename-safe prefix back into a human-readable bookmark name.
    Example: 'STG1_NIVERA_RYAN_N' -> 'STG1 NIVERA,RYAN N'
    """
    parts = safe_prefix.split('_')
    if len(parts) >= 3:
        rate = parts[0]
        last = parts[1]
        first = " ".join(parts[2:])
        return f"{rate} {last},{first}"
    return safe_prefix.replace("_", " ")

def _build_prefix_variants(safe_prefix):
    """
    Build a set of possible prefixes that may exist across outputs.
    This is needed because some files may use commas vs underscores.
    """
    variants = set()
    variants.add(safe_prefix)
    variants.add(safe_prefix.lstrip("_"))

    parts = safe_prefix.split("_")
    if len(parts) >= 3:
        rate = parts[0]
        last = parts[1]
        first = "_".join(parts[2:])

        # Variant with comma between last and first (PG-13 newer style)
        variants.add(f"{rate}_{last},{first}".lstrip("_"))

        # Variant where commas were replaced with underscores earlier
        variants.add(f"{rate}_{last}_{first}".lstrip("_"))

    # Add comma-stripped
    variants.add(safe_prefix.replace(",", "_").lstrip("_"))
    return sorted(list(variants), key=len, reverse=True)

def _append_pdf(writer, file_path, bookmark_title, parent_bookmark=None):
    if not os.path.exists(file_path):
        log(f"  - INFO: File not found for bookmark '{bookmark_title}'. Looked for: {os.path.basename(file_path)}")
        return 0

    try:
        reader = PdfReader(file_path)
        num_pages_added = len(reader.pages)
        if num_pages_added == 0:
            log(f"  - ⚠️ WARNING: PDF file '{os.path.basename(file_path)}' is empty (0 pages). Skipping.")
            return 0

        page_num_before_add = len(writer.pages)

        writer.add_outline_item(bookmark_title, page_num_before_add, parent=parent_bookmark)
        log(f"  - Adding bookmark '{bookmark_title}' at page {page_num_before_add + 1}")

        for page in reader.pages:
            writer.add_page(page)

        log(f"    ... Appended {os.path.basename(file_path)} ({num_pages_added} pages)")
        return num_pages_added
    except Exception as e:
        log(f"  - ❗️ CRITICAL ERROR appending PDF {os.path.basename(file_path)}: {e}")
        return 0

def _pick_first_matching_file(folder, prefix_variants):
    """
    Return the first file in folder whose name starts with any of the variants.
    """
    if not os.path.exists(folder):
        return None

    all_files = os.listdir(folder)
    for v in prefix_variants:
        matches = [f for f in all_files if f.startswith(v)]
        if matches:
            return matches[0]
    return None

def _find_all_matching_files(folder, prefix_variants):
    """
    Return all files in folder whose name starts with any of the variants.
    """
    if not os.path.exists(folder):
        return []

    out = []
    all_files = os.listdir(folder)
    for f in all_files:
        for v in prefix_variants:
            if f.startswith(v):
                out.append(f)
                break
    return sorted(list(set(out)))

def _pg13_bookmark_title(pg13_filename):
    """
    Create a friendly bookmark name from a PG-13 filename.

    Supports:
      ...__PG13__ALL_MISSIONS__MM-DD-YYYY_TO_MM-DD-YYYY.pdf
      ...__SEA_PAY_PG13__SHIP__...
      ... older patterns
    """
    base = os.path.splitext(pg13_filename)[0]

    m_all = re.search(r'__PG13__ALL_MISSIONS__([0-9]{2}-[0-9]{2}-[0-9]{4})_TO_([0-9]{2}-[0-9]{2}-[0-9]{4})', base, re.IGNORECASE)
    if m_all:
        return f"ALL MISSIONS ({m_all.group(1)} to {m_all.group(2)})"

    m_ship = re.search(r'__SEA_PAY_PG13__([A-Z0-9_ ]+?)__', base, re.IGNORECASE)
    if m_ship:
        return m_ship.group(1).replace("_", " ").strip()

    # Fallback: just the filename
    return base

def merge_all_pdfs():
    os.makedirs(PACKAGE_FOLDER, exist_ok=True)

    final_package_path = os.path.join(PACKAGE_FOLDER, "MERGED_SEA_PAY_PACKAGE.pdf")
    writer = PdfWriter()

    log("=== BOOKMARKED PACKAGE MERGE STARTED ===")

    all_prefixes = _get_file_prefixes_from_folder(SUMMARY_PDF_FOLDER)
    if not all_prefixes:
        log("MERGE FAILED → No member summary PDFs found in SUMMARY_PDF folder. Cannot determine which members to process.")
        writer.close()
        return

    log(f"Found {len(all_prefixes)} unique member file prefixes: {all_prefixes}")

    for safe_key_prefix in all_prefixes:
        member_bookmark_name = _create_bookmark_name(safe_key_prefix)
        prefix_variants = _build_prefix_variants(safe_key_prefix)

        log(f"Processing prefix: '{safe_key_prefix}' variants={prefix_variants} for member: '{member_bookmark_name}'")

        parent_page_num = len(writer.pages)
        parent_bookmark = writer.add_outline_item(member_bookmark_name, parent_page_num)
        log(f"  - Creating parent bookmark '{member_bookmark_name}' at page {parent_page_num + 1}")

        summary_file = os.path.join(SUMMARY_PDF_FOLDER, f"{safe_key_prefix}_SUMMARY.pdf")
        _append_pdf(writer, summary_file, "Summary", parent_bookmark)

        # TORIS
        toris_match = _pick_first_matching_file(TORIS_CERT_FOLDER, prefix_variants)
        if toris_match:
            _append_pdf(writer, os.path.join(TORIS_CERT_FOLDER, toris_match), "TORIS Certification", parent_bookmark)
        else:
            log(f"  - INFO: No TORIS Cert file found for prefix variants: {prefix_variants}")

        # PG-13s
        pg13_files = _find_all_matching_files(SEA_PAY_PG13_FOLDER, prefix_variants)
        if pg13_files:
            pg13_parent_bookmark = writer.add_outline_item("PG-13s", len(writer.pages), parent=parent_bookmark)
            for pg13_file in pg13_files:
                title = _pg13_bookmark_title(pg13_file)
                _append_pdf(writer, os.path.join(SEA_PAY_PG13_FOLDER, pg13_file), title, pg13_parent_bookmark)
        else:
            log(f"  - INFO: No PG-13 files found for prefix variants: {prefix_variants}")

    log(f"Finalizing PDF. Total pages to write: {len(writer.pages)}")

    if len(writer.pages) > 0:
        try:
            with open(final_package_path, "wb") as f:
                writer.write(f)
            log(f"✅ BOOKMARKED PACKAGE CREATED → {os.path.basename(final_package_path)}")
        except Exception as e:
            log(f"❗️CRITICAL ERROR writing final PDF: {e}")
    else:
        log("MERGE FAILED → No pages were added to the final package. Check file paths and prefixes in the log.")

    writer.close()
    log("PACKAGE MERGE COMPLETE")
