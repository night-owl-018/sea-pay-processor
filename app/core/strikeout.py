import os
import shutil
from datetime import datetime
import io
import re

import pytesseract
from pdf2image import convert_from_path
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from pytesseract import Output

from app.core.logger import log


# ------------------------------------------------
# DATE VARIANT BUILDER (for matching skipped rows)
# ------------------------------------------------

def _build_date_variants(date_str):
    variants = set()
    try:
        dt = datetime.strptime(date_str, "%m/%d/%Y")
    except Exception:
        return {date_str}

    variants.add(date_str)
    variants.add(f"{dt.month}/{dt.day}/{dt.year}")
    variants.add(f"{dt.month}/{dt.day}/{dt.year % 100:02d}")
    variants.add(f"{dt.month:02d}/{dt.day:02d}/{dt.year % 100:02d}")

    return variants


# ------------------------------------------------
# STRIKEOUT ENGINE
# ------------------------------------------------

def mark_sheet_with_strikeouts(
    original_pdf,
    skipped_duplicates,
    skipped_unknown,
    output_path,
    extracted_total_days,
    computed_total_days,
    strike_color="black",
):
    """
    Draws strikeout lines on the TORIS Sea Duty Certification Sheet.

    • Strikes all UNKNOWN / DUPLICATE rows from parsing
    • Always strikes any row whose text contains 'SBTT'
    • Strikes once per invalid event, at the DATE row y-position
    • Total Sea Pay Days is struck/overwritten only if the number is wrong
    """

    # Color mapping (black / red)
    color_map = {
        "black": (0, 0, 0),
        "red": (1, 0, 0),
    }
    rgb = color_map.get(strike_color.lower(), (0, 0, 0))

    try:
        log(f"MARKING SHEET START → {os.path.basename(original_pdf)}")

        # Build target sets from parser results
        targets_invalid = {(u["date"], u["occ_idx"]) for u in skipped_unknown}
        targets_dup = {(d["date"], d["occ_idx"]) for d in skipped_duplicates}
        all_targets = targets_invalid.union(targets_dup)

        pages = convert_from_path(original_pdf)
        row_list = []

        # ------------------------------------------------
        # BUILD ROWS & OCR tokens
        # ------------------------------------------------
        all_dates = {d for (d, _) in all_targets}
        date_variants_map = {d: _build_date_variants(d) for d in all_dates}

        ocr_tokens = {}  # page_index -> list of (txt, left, top, w, h)

        for page_index, img in enumerate(pages):
            log(f"  BUILDING ROWS FROM PAGE {page_index+1}/{len(pages)}")

            data = pytesseract.image_to_data(img, output_type=Output.DICT)
            img_w, img_h = img.size
            scale_y = letter[1] / float(img_h)

            tokens = []
            page_token_list = []

            for j in range(len(data["text"])):
                txt = data["text"][j].strip()
                if not txt:
                    continue

                left = data["left"][j]
                top = data["top"][j]
                width = data["width"][j]
                height = data["height"][j]

                page_token_list.append((txt, left, top, width, height))

                center_y_img = top + height / 2.0
                center_from_bottom_px = img_h - center_y_img
                y = center_from_bottom_px * scale_y

                tokens.append({"text": txt.upper(), "y": y})

            ocr_tokens[page_index] = page_token_list

            # Sort downward (top row has largest y)
            tokens.sort(key=lambda t: -t["y"])

            # Group into visual rows by y-closeness
            visual_rows = []
            current_row = []
            last_y = None
            threshold = 5.5

            for tok in tokens:
                if last_y is None:
                    current_row = [tok]
                    last_y = tok["y"]
                    continue

                if abs(tok["y"] - last_y) <= threshold:
                    current_row.append(tok)
                    last_y = tok["y"]
                else:
                    visual_rows.append(current_row)
                    current_row = [tok]
                    last_y = tok["y"]

            if current_row:
                visual_rows.append(current_row)

            # Build row objects
            tmp_rows = []
            for row in visual_rows:
                y_avg = sum(t["y"] for t in row) / len(row)
                text = " ".join(t["text"] for t in row)
                tmp_rows.append({
                    "page": page_index,
                    "y": y_avg,
                    "text": text,
                    "date": None,
                    "occ_idx": None,
                })

            # Top-first
            tmp_rows.sort(key=lambda r: -r["y"])

            # Attach date/occ_idx ONLY for dates we already know from parser
            date_counters = {d: 0 for d in all_dates}
            for row in tmp_rows:
                for d in all_dates:
                    variants = date_variants_map[d]
                    if any(v in row["text"] for v in variants):
                        date_counters[d] += 1
                        row["date"] = d
                        row["occ_idx"] = date_counters[d]
                        break

            row_list.extend(tmp_rows)

        # ------------------------------------------------
        # PATCH: ENSURE SBTT ROWS HAVE DATE/OCC_IDX
        # (SBTT always invalid, regardless of parser)
        # ------------------------------------------------
        sbtt_counters = {}  # date -> count

        date_regex = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")

        for row in row_list:
            if "SBTT" not in row["text"]:
                continue

            # If date not already known, parse it from the text
            if not row.get("date"):
                m = date_regex.search(row["text"])
                if m:
                    row["date"] = m.group(1)

            if not row.get("date"):
                # If still no date, we cannot anchor it; log and skip
                log(f"    SBTT ROW WITHOUT DATE → '{row['text']}'")
                continue

            # Ensure occ_idx is unique for this date
            if not row.get("occ_idx"):
                sbtt_counters[row["date"]] = sbtt_counters.get(row["date"], 0) + 1
                row["occ_idx"] = sbtt_counters[row["date"]]

            # Mark this (date, occ_idx) as a target to strike
            all_targets.add((row["date"], row["occ_idx"]))

        # ------------------------------------------------
        # MAP INVALID / SBTT / DUPLICATE EVENTS TO DATE-Y
        # ------------------------------------------------
        # Group all rows by (date, occ_idx)
        rows_by_key = {}
        for r in row_list:
            k = (r.get("date"), r.get("occ_idx"))
            rows_by_key.setdefault(k, []).append(r)

        strike_targets = {}  # page -> list of y-values

        for key in all_targets:
            if not key[0] or not key[1]:
                continue  # missing date or occ_idx

            group = rows_by_key.get(key)
            if not group:
                continue

            # Use highest y (top-most) row for this date/occurrence
            date_row = max(group, key=lambda r: r["y"])
            y_anchor = date_row["y"]
            page_idx = date_row["page"]

            strike_targets.setdefault(page_idx, []).append(y_anchor)
            log(f"    STRIKE EVENT {key[0]} OCC#{key[1]} PAGE {page_idx+1} Y={y_anchor:.1f}")

        # ------------------------------------------------
        # TOTAL SEA PAY DAYS CORRECTION
        # ------------------------------------------------
        total_row = None
        for row in row_list:
            if (
                "TOTAL" in row["text"]
                and "SEA" in row["text"]
                and "PAY" in row["text"]
                and "DAYS" in row["text"]
            ):
                total_row = row
                break

        total_overlay = None

        if total_row:
            page_idx = total_row["page"]
            target_y_pdf = total_row["y"]

            page_img = pages[page_idx]
            width_img, height_img = page_img.size
            scale_x = letter[0] / float(width_img)

            tokens_page = ocr_tokens[page_idx]

            old_start_x_pdf = None
            old_end_x_pdf = None

            # Find where the original total-number sits
            for (txt, left, top, w, h) in tokens_page:
                if re.fullmatch(r"\d+", txt):
                    center_y_img = top + h / 2.0
                    center_from_bottom_px = height_img - center_y_img
                    y_pdf = center_from_bottom_px * (letter[1] / float(height_img))

                    if abs(y_pdf - target_y_pdf) < 3:
                        old_start_x_pdf = left * scale_x
                        old_end_x_pdf = (left + w) * scale_x
                        break

            if old_start_x_pdf is None:
                old_start_x_pdf = 260
                old_end_x_pdf = 300

            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=letter)
            c.setFont("Helvetica", 10)

            three_spaces_width = c.stringWidth("   ", "Helvetica", 10)
            correct_x_pdf = old_end_x_pdf + three_spaces_width
            strike_end_x = correct_x_pdf - three_spaces_width

            c.setLineWidth(0.8)
            c.setStrokeColorRGB(*rgb)

            # Only strike/overwrite if the numbers differ or if we have no extracted value
            if (
                extracted_total_days is None
                or computed_total_days is None
                or extracted_total_days != computed_total_days
            ):
                c.line(old_start_x_pdf, target_y_pdf, strike_end_x, target_y_pdf)
                if computed_total_days is not None:
                    c.drawString(correct_x_pdf, target_y_pdf, str(computed_total_days))

            c.save()
            buf.seek(0)
            total_overlay = PdfReader(buf)

        # ------------------------------------------------
        # NORMAL STRIKEOUT LINES (FULL WIDTH, DATE-Y ONLY)
        # ------------------------------------------------
        overlays = []
        for p in range(len(pages)):
            ys = strike_targets.get(p)
            if not ys:
                overlays.append(None)
                continue

            # Deduplicate near-identical y-values to avoid double lines
            cleaned = []
            for y in ys:
                if not any(abs(y - c) < 0.5 for c in cleaned):
                    cleaned.append(y)

            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=letter)
            c.setLineWidth(0.8)
            c.setStrokeColorRGB(*rgb)

            # Full-width strike across the row
            for y in cleaned:
                c.line(40, y, 550, y)

            c.save()
            buf.seek(0)
            overlays.append(PdfReader(buf))

        # ------------------------------------------------
        # APPLY OVERLAYS
        # ------------------------------------------------
        reader = PdfReader(original_pdf)
        writer = PdfWriter()

        for i, page in enumerate(reader.pages):
            if total_overlay and total_row and i == total_row["page"]:
                page.merge_page(total_overlay.pages[0])

            if i < len(overlays) and overlays[i] is not None:
                page.merge_page(overlays[i].pages[0])

            try:
                page.compress_content_streams()
            except Exception:
                pass

            writer.add_page(page)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            writer.write(f)

        log(f"MARKED SHEET CREATED → {os.path.basename(output_path)}")

    except Exception as e:
        log(f"⚠️ MARKING FAILED → {e}")
        try:
            shutil.copy2(original_pdf, output_path)
            log(f"FALLBACK COPY CREATED → {os.path.basename(original_pdf)}")
        except Exception as e2:
            log(f"⚠️ FALLBACK COPY FAILED → {e2}")
