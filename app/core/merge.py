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
    if not os.path.exists(file_path):
        log(f"  - Skipping bookmark '{bookmark_title}': File not found at {file_path}")
        return 0
        
    try:
        reader = PdfReader(file_path)
        num_pages_added = len(reader.pages)
        page_num_before_add = len(writer.pages)
        
        # Add the bookmark pointing to the first new page
        writer.add_outline_item(bookmark_title, page_num_before_add, parent=parent_bookmark)
        log(f"  - Adding bookmark '{bookmark_title}' at page {page_num_before_add + 1}")

        for page in reader.pages:
            writer.add_page(page)
            
        log(f"    ... Appended {os.path.basename(file_path)} ({num_pages_added} pages)")
        return num_pages_added
    except Exception as e:
        log(f"  - ❗️ ERROR appending PDF {os.path.basename(file_path)}: {e}")
        return 0

def merge_all_pdfs():
    """
    Merges all output PDFs into a single, bookmarked package.
    Creates a nested table of contents for easy navigation.
    """
    os.makedirs(PACKAGE_FOLDER, exist_ok=True)
    
    final_package_path = os.path.join(PACKAGE_FOLDER, "MERGED_SEA_PAY_PACKAGE.pdf")
    writer = PdfWriter()
    
    # 1. Get a master list of all members from the summary files
    # This is the most reliable source for the list of members processed.
    all_members = _get_members_from_files(SUMMARY_PDF_FOLDER)
    if not all_members:
        log("MERGE SKIPPED → No member summary PDFs found to create a package.")
        return

    log("=== BOOKMARKED PACKAGE MERGE STARTED ===")
    
    # 2. Loop through each member to build their section
    for member_key in all_members:
        log(f"Processing member: {member_key}")
        
        # Create the filename-safe version of the key
        safe_key_prefix = member_key.replace(",", "").replace(" ", "_")
        
        # Get current page number to create the main parent bookmark for this member
        parent_page_num = len(writer.pages)
        parent_bookmark = writer.add_outline_item(member_key, parent_page_num)
        log(f"Creating parent bookmark '{member_key}' at page {parent_page_num + 1}")
        
        # 3. Find and append this member's files in a specific order
        
        # Add Summary PDF
        summary_file = os.path.join(SUMMARY_PDF_FOLDER, f"{safe_key_prefix}_SUMMARY.pdf")
        _append_pdf(writer, summary_file, "Summary", parent_bookmark)
        
        # Add TORIS Cert PDF
        # Find the TORIS file that contains this member's safe key prefix in its name.
        try:
            toris_files = [f for f in os.listdir(TORIS_CERT_FOLDER) if safe_key_prefix in f]
            if toris_files:
                # Assuming the first match is the correct one
                toris_file_path = os.path.join(TORIS_CERT_FOLDER, toris_files[0])
                _append_pdf(writer, toris_file_path, "TORIS Certification", parent_bookmark)
        except FileNotFoundError:
            log(f"  - Skipping TORIS Cert: Folder not found at {TORIS_CERT_FOLDER}")


        # Add all PG-13 PDFs for this member
        try:
            pg13_files = [f for f in os.listdir(SEA_PAY_PG13_FOLDER) if safe_key_prefix in f]
            if pg13_files:
                pg13_parent_bookmark = writer.add_outline_item("PG-13s", len(writer.pages), parent=parent_bookmark)
                for pg13_file in sorted(pg13_files):
                    # Extract ship name from filename like 'STG1_NIVERA_RYAN_PG13_USS_CHAFEE.pdf'
                    match = re.search(r'PG13_(.+)\.pdf', pg13_file, re.IGNORECASE)
                    ship_name = match.group(1).replace("_", " ") if match else pg13_file
                    bookmark_title = f"{ship_name}"
                    pg13_file_path = os.path.join(SEA_PAY_PG13_FOLDER, pg13_file)
                    _append_pdf(writer, pg13_file_path, bookmark_title, pg13_parent_bookmark)
        except FileNotFoundError:
            log(f"  - Skipping PG-13s: Folder not found at {SEA_PAY_PG13_FOLDER}")


    # 4. Write the final merged file
    if len(writer.pages) > 0:
        try:
            with open(final_package_path, "wb") as f:
                writer.write(f)
            log(f"BOOKMARKED PACKAGE CREATED → {os.path.basename(final_package_path)}")
        except Exception as e:
            log(f"❗️CRITICAL ERROR writing final PDF: {e}")
    else:
        log("MERGE CANCELED → No content was added to the final package.")
        
    writer.close()
    log("PACKAGE MERGE COMPLETE")

# 🔹 --- END OF PATCH --- 🔹
