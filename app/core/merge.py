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

# 🔹 --- START OF PATCH --- 🔹

def _get_members_from_files(folder):
    """
    Scans a folder and extracts a sorted list of unique member keys
    from the PDF filenames. Assumes format RATE_LAST_FIRST_...
    """
    if not os.path.exists(folder):
        return []
    
    member_keys = set()
    files = [f for f in os.listdir(folder) if f.lower().endswith(".pdf")]
    
    for f in files:
        # Assumes format like 'STG1_NIVERA_RYAN_...'
        parts = f.split('_')
        if len(parts) >= 3:
            # Reconstruct the member_key: 'STG1 NIVERA,RYAN'
            rate = parts[0]
            last = parts[1]
            first = parts[2]
            member_key = f"{rate} {last},{first}"
            member_keys.add(member_key)
            
    return sorted(list(member_keys))

def _append_pdf(writer, file_path, bookmark_title, parent_bookmark=None):
    """
    Helper to append a PDF to the writer and add an optional bookmark.
    Returns the number of pages added.
    """
    # Add detailed logging
    if not os.path.exists(file_path):
        log(f"  - ❗️ SKIPPING: File not found for bookmark '{bookmark_title}' at path: {file_path}")
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

def merge_all_pdfs():
    """
    Merges all output PDFs into a single, bookmarked package.
    Creates a nested table of contents for easy navigation.
    """
    os.makedirs(PACKAGE_FOLDER, exist_ok=True)
    
    final_package_path = os.path.join(PACKAGE_FOLDER, "MERGED_SEA_PAY_PACKAGE.pdf")
    writer = PdfWriter()
    
    # Add detailed logging
    log("=== BOOKMARKED PACKAGE MERGE STARTED ===")
    
    all_members = _get_members_from_files(SUMMARY_PDF_FOLDER)
    if not all_members:
        log("MERGE FAILED → No member summary PDFs found in SUMMARY_PDF folder. Cannot determine which members to process.")
        writer.close()
        return

    log(f"Found {len(all_members)} members to process: {all_members}")
    
    for member_key in all_members:
        log(f"Processing member: '{member_key}'")
        
        safe_key_prefix = member_key.replace(",", "").replace(" ", "_")
        log(f"  - Using safe file prefix: '{safe_key_prefix}'")
        
        parent_page_num = len(writer.pages)
        parent_bookmark = writer.add_outline_item(member_key, parent_page_num)
        log(f"  - Creating parent bookmark '{member_key}' at page {parent_page_num + 1}")
        
        # Find and append Summary PDF
        summary_file = os.path.join(SUMMARY_PDF_FOLDER, f"{safe_key_prefix}_SUMMARY.pdf")
        _append_pdf(writer, summary_file, "Summary", parent_bookmark)
        
        # Find and append TORIS Cert PDF
        try:
            toris_files = [f for f in os.listdir(TORIS_CERT_FOLDER) if safe_key_prefix in f]
            if toris_files:
                toris_file_path = os.path.join(TORIS_CERT_FOLDER, toris_files[0])
                _append_pdf(writer, toris_file_path, "TORIS Certification", parent_bookmark)
            else:
                log(f"  - INFO: No TORIS Cert file found for prefix '{safe_key_prefix}'")
        except FileNotFoundError:
            log(f"  - WARNING: TORIS Cert folder not found at {TORIS_CERT_FOLDER}")

        # Find and append all PG-13 PDFs for this member
        try:
            pg13_files = [f for f in os.listdir(SEA_PAY_PG13_FOLDER) if safe_key_prefix in f]
            if pg13_files:
                pg13_parent_bookmark = writer.add_outline_item("PG-13s", len(writer.pages), parent=parent_bookmark)
                for pg13_file in sorted(pg13_files):
                    match = re.search(r'PG13_(.+)\.pdf', pg13_file, re.IGNORECASE)
                    ship_name = match.group(1).replace("_", " ") if match else pg13_file
                    bookmark_title = f"{ship_name}"
                    pg13_file_path = os.path.join(SEA_PAY_PG13_FOLDER, pg13_file)
                    _append_pdf(writer, pg13_file_path, bookmark_title, pg13_parent_bookmark)
            else:
                log(f"  - INFO: No PG-13 files found for prefix '{safe_key_prefix}'")
        except FileNotFoundError:
            log(f"  - WARNING: PG-13 folder not found at {SEA_PAY_PG13_FOLDER}")

    log(f"Finalizing PDF. Total pages to write: {len(writer.pages)}")

    if len(writer.pages) > 0:
        try:
            with open(final_package_path, "wb") as f:
                writer.write(f)
            log(f"✅ BOOKMARKED PACKAGE CREATED → {os.path.basename(final_package_path)}")
        except Exception as e:
            log(f"❗️CRITICAL ERROR writing final PDF: {e}")
    else:
        log("MERGE FAILED → No pages were added to the final package. Check file paths and prefixes.")
        
    writer.close()
    log("PACKAGE MERGE COMPLETE")

# 🔹 --- END OF PATCH --- 🔹
