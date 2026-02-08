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
    
    The name is added ABOVE the "PRINTED NAME OF CERTIFYING OFFICER" line,
    dynamically finding the label position rather than using fixed coordinates.
    
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
        
        # Read the PDF to find the position of "PRINTED NAME OF CERTIFYING OFFICER"
        reader = PdfReader(input_pdf_path)
        target_page_index = len(reader.pages) - 1  # Last page (where signature section is)
        target_page = reader.pages[target_page_index]
        
        # Try to find the Y-position by searching in the page's content stream
        y_position = None
        x_position = 63  # Default X position
        
        try:
            # Extract text to verify the label exists
            text_content = target_page.extract_text()
            
            if "PRINTED NAME OF CERTIFYING OFFICER" in text_content:
                # The label exists - now we need to find its position
                # Since PyPDF2 doesn't give us easy coordinate access, we'll use pdfplumber
                try:
                    import pdfplumber
                    
                    with pdfplumber.open(input_pdf_path) as pdf:
                        page = pdf.pages[target_page_index]
                        
                        # Search for the text
                        words = page.extract_words()
                        
                        for word in words:
                            if "PRINTED" in word['text'] and "NAME" in text_content:
                                # Found it! The word dict has 'top', 'bottom', 'x0', 'x1'
                                # Convert from pdfplumber coords (top-down) to ReportLab coords (bottom-up)
                                page_height = float(page.height)
                                label_y_from_top = word['top']
                                label_y_from_bottom = page_height - label_y_from_top
                                
                                # Place name about 12-15 points ABOVE the label
                                y_position = label_y_from_bottom + 15
                                x_position = word['x0']  # Align with label
                                
                                log(f"Found 'PRINTED NAME' at Y={label_y_from_bottom:.1f}, placing name at Y={y_position:.1f}")
                                break
                
                except ImportError:
                    log("pdfplumber not available, using fallback positioning")
                except Exception as e:
                    log(f"Error using pdfplumber: {e}")
        
        except Exception as e:
            log(f"Error extracting text: {e}")
        
        # If we couldn't find it dynamically, use a reasonable default
        if y_position is None:
            y_position = 165
            log(f"Using default Y position: {y_position}")
        
        # Create an overlay with the certifying officer name
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.setFont("Helvetica-Bold", 10)
        
        c.drawString(x_position, y_position, certifying_officer_name)
        c.save()
        buf.seek(0)
        
        # Read the existing PDF
        reader = PdfReader(input_pdf_path)
        overlay = PdfReader(buf)
        writer = PdfWriter()
        
        # Merge the overlay onto the first page (TORIS sheets are typically single page)
        # For multi-page TORIS sheets, we add to the last page
        for i, page in enumerate(reader.pages):
            if i == len(reader.pages) - 1:  # Last page
                page.merge_page(overlay.pages[0])
            writer.add_page(page)
        
        # Write the output
        with open(output_pdf_path, "wb") as f:
            writer.write(f)
        
        log(f"ADDED CERTIFYING OFFICER TO TORIS → {certifying_officer_name} in {os.path.basename(output_pdf_path)}")
        
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
