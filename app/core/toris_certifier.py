"""
Module to add certifying officer information to TORIS certification sheets.
"""

import os
import io
import re
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

                # 1) Find the specific "PRINTED NAME OF CERTIFYING OFFICER" label
                label_word = None
                label_top = None  # y from top

                for i, w in enumerate(words):
                    if w.get("text", "").upper() == "PRINTED":
                        lookahead = [
                            words[i + j].get("text", "").upper()
                            for j in range(1, 10)
                            if (i + j) < len(words)
                        ]

                        # Expect: PRINTED NAME OF CERTIFYING OFFICER ...
                        if ("NAME" in lookahead[:3]) and ("CERTIFYING" in lookahead) and ("OFFICER" in lookahead):
                            label_word = w
                            label_top = float(w["top"])
                            log(f"Found 'PRINTED NAME OF CERTIFYING OFFICER' at Y={label_top:.1f} from top")
                            break

                if label_word is None:
                    log("Could not find 'PRINTED NAME OF CERTIFYING OFFICER' - using fallback")
                    raise Exception("Label not found")

                page_height = float(page.height)

                # 2) Find underscore lines above the label (the two lines we want to place text between)
                underscore_words = []
                for w in words:
                    t = (w.get("text") or "")
                    if re.fullmatch(r"_+", t) and len(t) >= 10:
                        top = float(w.get("top", 0.0))
                        if top < label_top:
                            # Keep it loose: ensure the underscore is in the same general horizontal region
                            # as the label (signature block area).
                            x0 = float(w.get("x0", 0.0))
                            x1 = float(w.get("x1", 0.0))

                            label_x0 = float(label_word.get("x0", 0.0))
                            label_x1 = float(label_word.get("x1", label_x0))

                            # Overlap-ish check with a generous range to survive layout shifts
                            if not (x1 < (label_x0 - 20) or x0 > (label_x1 + 320)):
                                underscore_words.append(w)

                # Sort by closest to the label (smallest vertical gap)
                underscore_words.sort(key=lambda w: (label_top - float(w.get("top", 0.0))))

                # Pick the two closest distinct underscore lines
                picked = []
                for w in underscore_words:
                    w_top = float(w.get("top", 0.0))
                    if not picked or abs(w_top - float(picked[-1].get("top", 0.0))) > 2:
                        picked.append(w)
                    if len(picked) == 2:
                        break

                if len(picked) < 2:
                    # Fallback to the old behavior (still dynamic relative to the label)
                    label_y_from_bottom = page_height - label_top
                    name_y = label_y_from_bottom + 13
                    name_x = 63  # keep your existing convention
                    log("Underscore lines not found reliably; using label-based fallback")
                    log(f"Label at Y={label_y_from_bottom:.1f} from bottom")
                    log(f"Placing '{certifying_officer_name}' at (X={name_x}, Y={name_y:.1f})")
                else:
                    # Convert to reportlab coords (from bottom) using the center of the underscore glyph boxes
                    y1 = page_height - ((float(picked[0]["top"]) + float(picked[0]["bottom"])) / 2.0)
                    y2 = page_height - ((float(picked[1]["top"]) + float(picked[1]["bottom"])) / 2.0)
                    mid_y = (y1 + y2) / 2.0

                    # Reportlab drawString uses baseline; a small font-based adjustment keeps it visually centered
                    font_size = 10
                    name_y = mid_y - (font_size * 0.35)

                    # Use the left edge of the underscore line to align with the signature block
                    name_x = float(picked[0]["x0"]) + 2

                    log(f"Underscore lines at Y={y1:.1f} and Y={y2:.1f} (from bottom)")
                    log(f"Placing '{certifying_officer_name}' at (X={name_x:.1f}, Y={name_y:.1f})")

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
