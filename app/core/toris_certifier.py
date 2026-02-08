"""
Module to add certifying officer information to TORIS certification sheets.
"""

import os
import io
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from app.core.logger import log
from app.core.config import get_certifying_officer_name


def add_certifying_officer_to_toris(input_pdf_path, output_pdf_path):
    """
    Add the certifying officer's name to a TORIS Sea Duty Certification Sheet PDF.
    
    Dynamically finds "PRINTED NAME OF CERTIFYING OFFICER" text and places the
    certifying officer name above it (between the two underscore lines).
    
    Args:
        input_pdf_path: Path to the TORIS sheet PDF
        output_pdf_path: Path where the updated PDF should be saved
    """
    try:
        # Get the certifying officer name
        certifying_officer_name = get_certifying_officer_name()
        
        if not certifying_officer_name:
            # If no certifying officer is set, just copy the file as-is
            log(f"NO CERTIFYING OFFICER SET → Copying TORIS as-is: {os.path.basename(input_pdf_path)}")
            if input_pdf_path != output_pdf_path:
                import shutil
                shutil.copy2(input_pdf_path, output_pdf_path)
            return
        
        # Use pdfplumber to find the exact position of "PRINTED NAME OF CERTIFYING OFFICER"
        try:
            import pdfplumber
            
            with pdfplumber.open(input_pdf_path) as pdf:
                # Process last page (where signature section is)
                page_index = len(pdf.pages) - 1
                page = pdf.pages[page_index]
                
                # Extract all text with positions
                words = page.extract_words()
                
                # Search for "PRINTED" which is the start of the label
                label_y = None
                label_x = None
                
                for word in words:
                    if word['text'] == 'PRINTED':
                        # Check if next words are "NAME OF CERTIFYING OFFICER"
                        # Found the label! Get its position
                        label_y = word['top']  # Y from top of page
                        label_x = word['x0']   # X position
                        log(f"Found 'PRINTED NAME...' at Y={label_y} from top")
                        break
                
                if label_y is None:
                    log("Could not find 'PRINTED NAME OF CERTIFYING OFFICER' - using fallback")
                    raise Exception("Text not found")
                
                # Convert from pdfplumber coordinates (Y=0 at top) to ReportLab (Y=0 at bottom)
                page_height = float(page.height)
                label_y_from_bottom = page_height - label_y
                
                # Place name about 12-14 points ABOVE the label
                # This puts it between the two underscore lines
                name_y = label_y_from_bottom + 13
                name_x = 63  # Standard left margin
                
                log(f"Label at Y={label_y_from_bottom:.1f} from bottom")
                log(f"Placing '{certifying_officer_name}' at (X={name_x}, Y={name_y:.1f})")
                
        except ImportError:
            log("⚠️ pdfplumber not installed - cannot dynamically position name")
            log("Install with: pip install pdfplumber")
            # Copy file without modification
            if input_pdf_path != output_pdf_path:
                import shutil
                shutil.copy2(input_pdf_path, output_pdf_path)
            return
            
        except Exception as e:
            log(f"⚠️ Error finding text position: {e}")
            # Copy file without modification
            if input_pdf_path != output_pdf_path:
                import shutil
                shutil.copy2(input_pdf_path, output_pdf_path)
            return
        
        # Create an overlay with the certifying officer name
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.setFont("Helvetica-Bold", 10)
        
        c.drawString(name_x, name_y, certifying_officer_name)
        c.save()
        buf.seek(0)
        
        # Read the existing PDF and merge overlay
        reader = PdfReader(input_pdf_path)
        overlay = PdfReader(buf)
        writer = PdfWriter()
        
        # Merge the overlay onto the last page
        for i, page in enumerate(reader.pages):
            if i == len(reader.pages) - 1:  # Last page
                page.merge_page(overlay.pages[0])
            writer.add_page(page)
        
        # Write the output
        with open(output_pdf_path, "wb") as f:
            writer.write(f)
        
        log(f"✅ ADDED CERTIFYING OFFICER TO TORIS → {certifying_officer_name}")
        
    except Exception as e:
        log(f"⚠️ ERROR ADDING CERTIFYING OFFICER TO TORIS → {e}")
        # On error, copy the original file
        if input_pdf_path != output_pdf_path:
            import shutil
            try:
                shutil.copy2(input_pdf_path, output_pdf_path)
                log(f"FALLBACK COPY CREATED → {os.path.basename(input_pdf_path)}")
            except Exception as e2:
                log(f"⚠️ FALLBACK COPY FAILED → {e2}")
