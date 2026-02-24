import os
import re
import json
import shutil
from datetime import datetime
import sys

from app.core.logger import (
    log,
    reset_progress,
    set_progress,
    add_progress_detail,
)
from app.core.config import (
    DATA_DIR,
    SEA_PAY_PG13_FOLDER,
    TORIS_CERT_FOLDER,
    REVIEW_JSON_PATH,
    PACKAGE_FOLDER,
)
from app.core.ocr import (
    ocr_pdf,
    strip_times,
    extract_member_name,
)
from app.core.parser import (
    parse_rows,
    extract_year_from_filename,
    group_by_ship,
    _safe_strptime,
)
from app.core.pdf_writer import make_pdf_for_ship
from app.core.strikeout import mark_sheet_with_strikeouts
from app.core.summary import write_summary_files
from app.core.merge import merge_all_pdfs
from app.core.rates import resolve_identity
from app.core.overrides import apply_overrides


# 🔹 PATCH: Cancel check helper - uses sys.modules to avoid circular import
def is_cancelled():
    """Check if processing has been cancelled"""
    try:
        routes = sys.modules.get("app.routes")
        if routes:
            return getattr(routes, "processing_cancelled", False)
        return False
    except Exception:
        return False


# =========================================================
# REFAC: Common helpers (keeps original behavior)
# =========================================================
def _cancel_and_exit(log_msg: str = "❌ PROCESSING CANCELLED BY USER", step_msg: str = "Cancelled by user") -> bool:
    """
    Standard cancel check + progress update.
    Returns True if cancelled (caller should return).
    """
    if is_cancelled():
        log(log_msg)
        set_progress(status="CANCELLED", percent=0, current_step=step_msg)
        return True
    return False


def _ensure_output_dirs():
    os.makedirs(SEA_PAY_PG13_FOLDER, exist_ok=True)
    os.makedirs(TORIS_CERT_FOLDER, exist_ok=True)


def _fresh_merge_package():
    if os.path.exists(PACKAGE_FOLDER):
        shutil.rmtree(PACKAGE_FOLDER)
        log("Deleted old PACKAGE folder for fresh merge")
    merge_all_pdfs()


def _apply_toris_certifier(toris_path: str, member_key: str):
    """Add certifying officer name to TORIS sheet (safe wrapper)."""
    from app.core.toris_certifier import add_certifying_officer_to_toris

    temp_toris = toris_path + ".tmp"
    try:
        add_certifying_officer_to_toris(toris_path, temp_toris, member_key=member_key)
        if os.path.exists(temp_toris):
            os.replace(temp_toris, toris_path)
    except Exception as e:
        log(f"⚠️ FAILED TO ADD CERTIFYING OFFICER TO TORIS → {e}")
        if os.path.exists(temp_toris):
            os.remove(temp_toris)


def _compute_overall_reporting_range(rp_list, fmt: str = "%m/%d/%Y", context: str = ""):
    """
    Accepts rp entries in either shape:
      {"start": ..., "end": ..., ...} or {"from": ..., "to": ..., ...}
    Values may be datetime or strings.
    Returns (overall_start_dt|None, overall_end_dt|None)
    """
    starts = []
    ends = []
    for x in (rp_list or []):
        if not isinstance(x, dict):
            continue

        s = x.get("start")
        e = x.get("end")
        if s is None:
            s = x.get("from")
        if e is None:
            e = x.get("to")

        if isinstance(s, str):
            s = _safe_strptime(s, fmt, context=f"{context} start")
        if isinstance(e, str):
            e = _safe_strptime(e, fmt, context=f"{context} end")

        if s:
            starts.append(s)
        if e:
            ends.append(e)

    return (min(starts) if starts else None, max(ends) if ends else None)


def _fmt_mdy(d: datetime) -> str:
    # Matches original formatting: month/day/year with no leading zeros.
    return f"{d.month}/{d.day}/{d.year}"


def _parse_mdy_or_default(val, fmt: str, context: str):
    """
    Preserve original behavior:
    - If val is already datetime, return it
    - If val is string, try _safe_strptime; if fails, default to datetime.now()
    """
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        return _safe_strptime(val, fmt, context=context) or datetime.now()
    return datetime.now()


def _build_events_followed(valid_periods_list, all_invalid_events, member_key: str):
    """
    Builds the exact same strings as the original code.
    """
    events_followed = []

    for p in valid_periods_list:
        start_dt = _parse_mdy_or_default(p.get("start"), "%m/%d/%Y", context=f"events_followed start {member_key}")
        end_dt = _parse_mdy_or_default(p.get("end"), "%m/%d/%Y", context=f"events_followed end {member_key}")
        days = (end_dt - start_dt).days + 1

        events_followed.append(
            f"{_fmt_mdy(start_dt)} TO {_fmt_mdy(end_dt)} | {p['ship']} | "
            f"PAY AUTHORIZED ({days} day{'s' if days != 1 else ''})"
        )

    for e in all_invalid_events:
        if not e.get("date"):
            continue
        try:
            dt_obj = datetime.strptime(e["date"], "%m/%d/%Y")
            date_str = _fmt_mdy(dt_obj)
        except Exception:
            date_str = e["date"]

        events_followed.append(f"{date_str} | {e['ship']} | {e['reason']}")

    return events_followed


def _build_tracker_lines(rate: str, last: str, first: str, valid_periods_list, all_invalid_events, member_key: str):
    """
    Builds the exact same strings as the original code.
    """
    tracker_lines = []

    for p in valid_periods_list:
        start_dt = _parse_mdy_or_default(p.get("start"), "%m/%d/%Y", context=f"tracker_lines start {member_key}")
        end_dt = _parse_mdy_or_default(p.get("end"), "%m/%d/%Y", context=f"tracker_lines end {member_key}")
        days = (end_dt - start_dt).days + 1

        tracker_lines.append(
            f"{rate} {last}, {first} | {p['ship']} | "
            f"{_fmt_mdy(start_dt)} TO {_fmt_mdy(end_dt)} "
            f"({days} day{'s' if days != 1 else ''}) | VALID"
        )

    for e in all_invalid_events:
        if not e.get("date"):
            continue
        try:
            dt_obj = datetime.strptime(e["date"], "%m/%d/%Y")
            date_str = _fmt_mdy(dt_obj)
        except Exception:
            date_str = e["date"]

        tracker_lines.append(
            f"{rate} {last}, {first} | {e['ship']} | "
            f"{date_str} | {e['reason']}"
        )

    return tracker_lines


def _build_valid_periods_from_rows(ship_map: dict):
    """
    Behavior-preserving:
    - Calls group_by_ship(ship_rows) exactly as before
    - Creates valid_periods_list entries with start/end/days
    """
    valid_periods_list = []
    for ship, ship_rows in ship_map.items():
        periods = group_by_ship(ship_rows)
        for g in periods:
            start_dt = g["start"]
            end_dt = g["end"]
            days = (end_dt - start_dt).days + 1
            valid_periods_list.append({"ship": ship, "start": start_dt, "end": end_dt, "days": days})
    valid_periods_list.sort(key=lambda p: p["start"])
    return valid_periods_list


# 🔹 =====================================================
# 🔹 PATCH: GRANULAR PROGRESS HELPER
# 🔹 =====================================================
class ProgressTracker:
    """
    Helper class to manage smooth, granular progress updates.
    Divides 100% progress into phases and sub-steps.
    """
    def __init__(self, total_files):
        self.total_files = max(total_files, 1)
        self.current_file = 0

        # Phase allocation (must sum to 100%)
        self.PHASE_FILE_PROCESSING = 85  # 85% for all file processing
        self.PHASE_SUMMARY = 5           # 5% for summary generation
        self.PHASE_MERGE = 10            # 10% for merging outputs

        # Sub-steps within each file (must sum to 100%)
        self.STEP_OCR = 20               # 20% OCR
        self.STEP_PARSE = 15             # 15% Parsing
        self.STEP_VALIDATION = 15        # 15% Validation
        self.STEP_REVIEW_STATE = 10      # 10% Building review state
        self.STEP_TORIS = 20             # 20% TORIS marking
        self.STEP_PG13 = 20              # 20% PG-13 generation

    def get_file_base_progress(self, file_index):
        """Get the starting progress % for a given file (0-indexed)"""
        return int((file_index / self.total_files) * self.PHASE_FILE_PROCESSING)

    def get_file_progress_range(self):
        """Get how much % each file is worth"""
        return self.PHASE_FILE_PROCESSING / self.total_files

    def update(self, file_index, sub_step_percent, step_name):
        """
        Update progress with granular sub-step tracking.
        """
        base = self.get_file_base_progress(file_index)
        file_range = self.get_file_progress_range()
        within_file = (sub_step_percent / 100.0) * file_range
        total = int(base + within_file)

        total = max(0, min(total, 100))

        set_progress(
            status="PROCESSING",
            percent=total,
            current_step=step_name
        )

    def phase_summary(self):
        """Update progress for summary phase"""
        percent = self.PHASE_FILE_PROCESSING + int(self.PHASE_SUMMARY * 0.5)
        set_progress(
            status="PROCESSING",
            percent=percent,
            current_step="Writing summary files"
        )

    def phase_merge(self):
        """Update progress for merge phase"""
        percent = self.PHASE_FILE_PROCESSING + self.PHASE_SUMMARY
        set_progress(
            status="PROCESSING",
            percent=percent,
            current_step="Merging output package"
        )

    def complete(self):
        """Mark as 100% complete"""
        set_progress(
            status="COMPLETE",
            percent=100,
            current_step="Complete"
        )


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
def extract_reporting_period(text, filename: str = ""):
    """
    Try to pull the "From: ... To: ..." reporting period from the OCR text.
    Fall back to a date range in the filename if needed.
    """
    pattern = r"From:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*To:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})"
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        from_raw = match.group(1)
        to_raw = match.group(2)
        try:
            start = datetime.strptime(from_raw, "%m/%d/%Y")
            end = datetime.strptime(to_raw, "%m/%d/%Y")
        except Exception:
            return None, None, ""
        return start, end, f"{from_raw} - {to_raw}"

    alt_pattern = r"(\d{1,2}_\d{1,2}_\d{4})\s*-\s*(\d{1,2}_\d{1,2}_\d{4})"
    m2 = re.search(alt_pattern, filename)
    if m2:
        try:
            s = datetime.strptime(m2.group(1).replace("_", "/"), "%m/%d/%Y")
            e = datetime.strptime(m2.group(2).replace("_", "/"), "%m/%d/%Y")
            return s, e, f"{m2.group(1)} - {m2.group(2)}"
        except Exception:
            return None, None, ""
    return None, None, ""


def extract_event_details(raw_text):
    """
    Extract event details (everything in parentheses) from raw text.
    Returns event string or empty string if no parentheses found.
    """
    match = re.search(r"\(([^)]+)\)", raw_text or "")
    return f"({match.group(1)})" if match else ""


def clear_pg13_folder():
    """Clear existing PG-13 outputs at the start of a run."""
    try:
        if not os.path.isdir(SEA_PAY_PG13_FOLDER):
            os.makedirs(SEA_PAY_PG13_FOLDER, exist_ok=True)
        for f in os.listdir(SEA_PAY_PG13_FOLDER):
            fp = os.path.join(SEA_PAY_PG13_FOLDER, f)
            if os.path.isfile(fp):
                os.remove(fp)
    except Exception as e:
        log(f"PG13 CLEAR ERROR → {e}")


# ---------------------------------------------------------
# MAIN PROCESSOR
# ---------------------------------------------------------
def process_all(strike_color: str = "black", consolidate_pg13: bool = False, consolidate_all_missions: bool = False):
    """
    Top-level processor with granular progress updates.
    """
    _ensure_output_dirs()

    clear_pg13_folder()
    reset_progress()

    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]
    if not files:
        log("NO INPUT FILES FOUND")
        set_progress(status="COMPLETE", percent=100)
        return

    total_files = len(files)
    progress = ProgressTracker(total_files)

    set_progress(
        status="PROCESSING",
        percent=0,
        current_step="Initializing",
        details={
            "files_processed": 0,
            "valid_days": 0,
            "invalid_events": 0,
            "pg13_created": 0,
            "toris_marked": 0,
        },
    )

    log("=== PROCESS STARTED ===")

    summary_data = {}
    review_state = {}

    files_processed_total = 0
    valid_days_total = 0
    invalid_events_total = 0
    pg13_total = 0
    toris_total = 0

    _TORIS_KEYWORDS = [
        "SEA DUTY CERTIFICATION",
        "TORIS",
        "PRINTED NAME OF CERTIFYING OFFICER",
        "SEA PAY",
        "FROM:",
        "REPORTING PERIOD",
    ]

    def _is_toris_sheet(ocr_text: str, filename: str) -> bool:
        up = (ocr_text or "").upper()
        if any(kw in up for kw in _TORIS_KEYWORDS):
            return True
        if re.search(r"Sea[\s_]Pay", filename, re.IGNORECASE):
            return True
        return False

    for idx, file in enumerate(sorted(files)):
        if _cancel_and_exit():
            return

        path = os.path.join(DATA_DIR, file)

        progress.update(idx, 0, f"[{idx+1}/{total_files}] OCR: {file}")
        log(f"OCR → {file}")

        try:
            raw = strip_times(ocr_pdf(path))
        except Exception as ocr_exc:
            log(f"PROCESS ERROR → OCR failed for {file}: {ocr_exc}")
            continue

        progress.update(idx, progress.STEP_OCR, f"[{idx+1}/{total_files}] OCR complete: {file}")

        if _cancel_and_exit():
            return

        if not _is_toris_sheet(raw, file):
            log(f"SKIP NON-TORIS FILE → '{file}' does not look like a Sea Duty Certification Sheet")
            continue

        sheet_start, sheet_end, _ = extract_reporting_period(raw, file)

        try:
            name = extract_member_name(raw, filename=file)
            log(f"NAME → {name}")
        except Exception as e:
            log(f"NAME ERROR → {e}")
            continue

        progress.update(
            idx,
            progress.STEP_OCR + progress.STEP_PARSE,
            f"[{idx+1}/{total_files}] Parsing: {file}",
        )

        year = extract_year_from_filename(file)
        rows, skipped_dupe, skipped_unknown = parse_rows(raw, year)

        if _cancel_and_exit():
            return

        progress.update(
            idx,
            progress.STEP_OCR + progress.STEP_PARSE + progress.STEP_VALIDATION,
            f"[{idx+1}/{total_files}] Validating: {file}",
        )

        groups = group_by_ship(rows)
        total_days = sum((g["end"] - g["start"]).days + 1 for g in groups)

        valid_days_total += total_days
        invalid_events_total += len(skipped_dupe) + len(skipped_unknown)
        add_progress_detail("valid_days", total_days)
        add_progress_detail("invalid_events", len(skipped_dupe) + len(skipped_unknown))

        rate, last, first = resolve_identity(name)
        member_key = f"{rate} {last},{first}"

        progress.update(
            idx,
            progress.STEP_OCR + progress.STEP_PARSE + progress.STEP_VALIDATION + progress.STEP_REVIEW_STATE,
            f"[{idx+1}/{total_files}] Building review: {file}",
        )

        if member_key not in review_state:
            review_state[member_key] = {
                "rate": rate,
                "last": last,
                "first": first,
                "sheets": [],
            }

        sheet_block = {
            "source_file": file,
            "reporting_period": {
                "from": sheet_start.strftime("%m/%d/%Y") if sheet_start else None,
                "to": sheet_end.strftime("%m/%d/%Y") if sheet_end else None,
            },
            "member_name_raw": name,
            "total_valid_days": total_days,
            "stats": {
                "total_rows": len(rows),
                "skipped_dupe_count": len(skipped_dupe),
                "skipped_unknown_count": len(skipped_unknown),
            },
            "rows": [],
            "invalid_events": [],
            "parsing_warnings": [],
            "parse_confidence": 1.0,
        }

        # 🔹 --- VALID ROWS: permanent positive event_index (unchanged behavior) ---
        for valid_idx, r in enumerate(rows):
            system_classification = {
                "is_valid": True,
                "reason": None,
                "explanation": "Valid sea pay day after TORIS parser filtering (non-training, non-duplicate, known ship).",
                "confidence": 1.0,
            }
            override = {"status": None, "reason": None, "source": None, "history": []}
            final_classification = {"is_valid": True, "reason": None, "source": "system"}

            sheet_block["rows"].append({
                "event_index": valid_idx,
                "date": r.get("date"),
                "ship": r.get("ship"),
                "event": extract_event_details(r.get("raw", "")),
                "occ_idx": r.get("occ_idx"),
                "raw": r.get("raw", ""),
                "is_inport": bool(r.get("is_inport", False)),
                "inport_label": r.get("inport_label"),
                "is_mission": r.get("is_mission"),
                "label": r.get("label"),
                "status": "valid",
                "status_reason": None,
                "confidence": 1.0,
                "system_classification": system_classification,
                "override": override,
                "final_classification": final_classification,
            })

        # 🔹 --- INVALID EVENTS: permanent negative event_index (unchanged behavior) ---
        invalid_events = []
        all_invalid_source = skipped_dupe + skipped_unknown

        for invalid_idx, e in enumerate(all_invalid_source):
            event_index = -(invalid_idx + 1)

            is_dupe = e in skipped_dupe
            if is_dupe:
                category = "duplicate"
                explanation = "Duplicate event for this date; another entry kept as primary sea pay event."
            else:
                raw_reason = (e.get("reason") or "").lower()
                if "in-port" in raw_reason or "shore" in raw_reason:
                    category = "shore_side_event"
                    explanation = "In-port shore-side training or non-sea-pay event."
                else:
                    category = "unknown"
                    explanation = "Unknown or non-platform event; no valid ship identified for sea pay."

            system_classification = {"is_valid": False, "reason": category, "explanation": explanation, "confidence": 1.0}
            override = {"status": None, "reason": None, "source": None, "history": []}
            final_classification = {"is_valid": False, "reason": category, "source": "system"}

            invalid_events.append({
                "event_index": event_index,
                "status": "invalid",
                "date": e.get("date"),
                "ship": e.get("ship"),
                "event": extract_event_details(e.get("raw", "")),
                "occ_idx": e.get("occ_idx"),
                "raw": e.get("raw", ""),
                "reason": e.get("reason", "Unknown"),
                "category": category,
                "source": "parser",
                "system_classification": system_classification,
                "override": override,
                "final_classification": final_classification,
            })

        sheet_block["invalid_events"] = invalid_events

        # Confidence heuristics (unchanged behavior)
        if len(skipped_unknown) > 0:
            sheet_block["parse_confidence"] = 0.7
            sheet_block["parsing_warnings"].append(f"{len(skipped_unknown)} unknown/suppressed entries detected.")
        if len(rows) == 0 and invalid_events:
            sheet_block["parse_confidence"] = 0.4
            sheet_block["parsing_warnings"].append("Sheet had no valid rows after parser filtering.")

        review_state[member_key]["sheets"].append(sheet_block)

        # Summary state (unchanged behavior)
        if member_key not in summary_data:
            summary_data[member_key] = {
                "rate": rate,
                "last": last,
                "first": first,
                "periods": [],
                "skipped_dupe": [],
                "skipped_unknown": [],
                "reporting_periods": [],
            }

        sd = summary_data[member_key]
        sd["reporting_periods"].append({"start": sheet_start, "end": sheet_end, "file": file})

        for g in groups:
            sd["periods"].append({
                "ship": g["ship"],
                "start": g["start"],
                "end": g["end"],
                "days": (g["end"] - g["start"]).days + 1,
                "sheet_file": file,
            })

        sd["skipped_unknown"].extend(skipped_unknown)
        sd["skipped_dupe"].extend(skipped_dupe)

        if _cancel_and_exit():
            return

        # TORIS marking
        progress.update(
            idx,
            progress.STEP_OCR + progress.STEP_PARSE + progress.STEP_VALIDATION + progress.STEP_REVIEW_STATE + progress.STEP_TORIS,
            f"[{idx+1}/{total_files}] Marking TORIS: {file}",
        )

        hf = sheet_start.strftime("%m-%d-%Y") if sheet_start else "UNKNOWN"
        ht = sheet_end.strftime("%m-%d-%Y") if sheet_end else "UNKNOWN"
        toris_filename = f"{rate}_{last}_{first}__TORIS_SEA_DUTY_CERT_SHEETS__{hf}_TO_{ht}.pdf".replace(" ", "_")
        toris_path = os.path.join(TORIS_CERT_FOLDER, toris_filename)

        if os.path.exists(toris_path):
            os.remove(toris_path)

        extracted_total_days = None
        computed_total_days = total_days

        mark_sheet_with_strikeouts(
            path,
            skipped_dupe,
            skipped_unknown,
            toris_path,
            extracted_total_days,
            computed_total_days,
            strike_color=strike_color,
        )
        
        if _cancel_and_exit("❌ CANCELLED DURING TORIS GENERATION"):
            return

        _apply_toris_certifier(toris_path, member_key)

        add_progress_detail("toris_marked", 1)
        toris_total += 1

        # PG-13 generation
        pg13_base_progress = (
            progress.STEP_OCR + progress.STEP_PARSE +
            progress.STEP_VALIDATION + progress.STEP_REVIEW_STATE +
            progress.STEP_TORIS
        )

        if not consolidate_all_missions:
            ship_map = {}
            for g in groups:
                ship_map.setdefault(g["ship"], []).append(g)

            ship_count = len(ship_map)
            for ship_idx, (ship, ship_periods) in enumerate(ship_map.items(), start=1):
                # keep original behavior: specific log line during PG-13 cancel
                if _cancel_and_exit(log_msg="❌ CANCELLED DURING PG-13 GENERATION", step_msg="Cancelled by user"):
                    return

                pg13_progress = pg13_base_progress + (progress.STEP_PG13 * (ship_idx / max(ship_count, 1)))
                progress.update(idx, pg13_progress, f"[{idx+1}/{total_files}] PG-13 {ship_idx}/{ship_count}: {ship}")

                make_pdf_for_ship(ship, ship_periods, name, consolidate=consolidate_pg13)
                add_progress_detail("pg13_created", 1)
                pg13_total += 1
        else:
            progress.update(
                idx,
                pg13_base_progress + progress.STEP_PG13,
                f"[{idx+1}/{total_files}] Preparing for all-missions consolidation",
            )

        add_progress_detail("files_processed", 1)
        files_processed_total += 1

        progress.update(idx, 100, f"[{idx+1}/{total_files}] Complete: {file}")

    # Consolidated all missions PG-13 (unchanged behavior + cancel support)
    if consolidate_all_missions:
        log("=== CREATING CONSOLIDATED ALL MISSIONS PG-13 FORMS ===")

        try:
            from app.core.pdf_writer import make_consolidated_all_missions_pdf
        except Exception as e:
            log(f"❌ ALL MISSIONS IMPORT FAILED → {e}")
            raise

        for member_key, member_data in summary_data.items():

            # ✅ PROPER CANCEL LOCATION
            if _cancel_and_exit("❌ CANCELLED DURING ALL-MISSIONS PG-13 GENERATION"):
                return

            try:
                ship_groups = {}
                for period in member_data.get("periods", []):
                    ship = period["ship"]
                    ship_groups.setdefault(ship, []).append(period)

                if ship_groups:
                    rp = member_data.get("reporting_periods", []) or []
                    overall_start, overall_end = _compute_overall_reporting_range(
                        rp,
                        context=f"process_all {member_key}"
                    )

                    make_consolidated_all_missions_pdf(
                        ship_groups,
                        member_key,
                        overall_start=overall_start,
                        overall_end=overall_end,
                        rate=member_data.get("rate"),
                        last=member_data.get("last"),
                        first=member_data.get("first"),
                    )

                    pg13_total += 1
                    add_progress_detail("pg13_created", 1)
                    log(f"Created consolidated all missions PG-13 for {member_key}")

            except Exception as e:
                log(f"❌ ALL MISSIONS PG-13 FAILED for {member_key} → {e}")
                raise

        log(f"=== COMPLETED {pg13_total} CONSOLIDATED ALL MISSIONS PG-13 FORMS ===")

    final_details = {
        "files_processed": files_processed_total,
        "valid_days": valid_days_total,
        "invalid_events": invalid_events_total,
        "pg13_created": pg13_total,
        "toris_marked": toris_total,
    }
    set_progress(details=final_details)

    progress.phase_summary()
    log("Writing summary files...")
    write_summary_files(summary_data)

    # Apply overrides (unchanged behavior)
    final_review_state = {}
    for member_key, member_data in review_state.items():
        final_review_state[member_key] = apply_overrides(member_key, member_data)

    # Write review JSON (unchanged behavior)
    try:
        os.makedirs(os.path.dirname(REVIEW_JSON_PATH), exist_ok=True)
        with open(REVIEW_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(final_review_state, f, indent=2, default=str)
        log(f"REVIEW JSON WRITTEN → {REVIEW_JSON_PATH}")

        original_path = REVIEW_JSON_PATH.replace(".json", "_ORIGINAL.json")
        shutil.copy(REVIEW_JSON_PATH, original_path)
        log(f"ORIGINAL REVIEW BACKUP CREATED → {original_path}")
    except Exception as e:
        log(f"REVIEW JSON ERROR → {e}")

    progress.phase_merge()
    log("Merging output package...")
    _fresh_merge_package()

    log("PROCESS COMPLETE")
    progress.complete()


# =========================================================
# REBUILD OUTPUTS FROM REVIEW JSON (NO OCR / NO PARSING)
# =========================================================
def rebuild_outputs_from_review(consolidate_pg13: bool = False, consolidate_all_missions: bool = False):
    """
    Rebuild PG-13, TORIS, summaries, and merged package strictly from REVIEW_JSON_PATH.
    """
    if not os.path.exists(REVIEW_JSON_PATH):
        log("REBUILD ERROR → REVIEW JSON NOT FOUND")
        return

    with open(REVIEW_JSON_PATH, "r", encoding="utf-8") as f:
        review_state = json.load(f)

    set_progress(status="PROCESSING", percent=0, current_step="Rebuilding outputs")

    _ensure_output_dirs()

    summary_data = {}
    pg13_total = 0
    toris_total = 0

    total_members = len(review_state)
    for member_idx, (member_key, member_data) in enumerate(review_state.items(), start=1):
        # keep original behavior: log line + cancelled progress
        if _cancel_and_exit(log_msg="❌ REBUILD CANCELLED BY USER", step_msg="Cancelled by user"):
            return

        member_progress = int((member_idx / max(total_members, 1)) * 85)
        set_progress(percent=member_progress, current_step=f"Rebuilding [{member_idx}/{total_members}]: {member_key}")

        rate = member_data["rate"]
        last = member_data["last"]
        first = member_data["first"]
        mi = member_data.get("mi") or member_data.get("middle_initial") or ""
        name = f"{first} {last}"

        summary_data[member_key] = {
            "rate": rate,
            "last": last,
            "first": first,
            "mi": mi,
            "valid_periods": [],
            "invalid_events": [],
            "events_followed": [],
            "tracker_lines": [],
            "reporting_periods": [],
        }

        all_valid_rows = []
        all_invalid_events = []

        for sheet in member_data.get("sheets", []):
            if sheet.get("reporting_period"):
                summary_data[member_key]["reporting_periods"].append({
                    "start": sheet["reporting_period"].get("from"),
                    "end": sheet["reporting_period"].get("to"),
                })

            all_valid_rows.extend(sheet.get("rows", []))

            for e in sheet.get("invalid_events", []):
                override_reason = e.get("status_reason") or e.get("override", {}).get("reason")
                final_reason = override_reason if override_reason else e.get("reason", "Invalid event")

                all_invalid_events.append({
                    "date": e.get("date"),
                    "ship": e.get("ship") or "UNKNOWN",
                    "occ_idx": e.get("occ_idx"),
                    "raw": e.get("raw", ""),
                    "reason": final_reason,
                    "category": e.get("category", ""),
                })

        ship_map = {}
        for r in all_valid_rows:
            ship = r.get("ship") or "UNKNOWN"
            ship_map.setdefault(ship, []).append(r)

        # Build valid periods list the same way (refactored)
        valid_periods_list = _build_valid_periods_from_rows(ship_map)

        # PG-13 generation (unchanged behavior)
        if not consolidate_all_missions:
            for ship, ship_rows in ship_map.items():
                periods = group_by_ship(ship_rows)
                make_pdf_for_ship(ship, periods, name, consolidate=consolidate_pg13)
                pg13_total += 1

        summary_data[member_key]["valid_periods"] = [(p["ship"], p["start"], p["end"]) for p in valid_periods_list]

        summary_data[member_key]["invalid_events"] = [
            (e["ship"], _safe_strptime(e["date"], "%m/%d/%Y", context=f"invalid_events {member_key}"), e["reason"])
            for e in all_invalid_events if e.get("date") and _safe_strptime(e["date"], "%m/%d/%Y")
        ]

        summary_data[member_key]["events_followed"] = _build_events_followed(valid_periods_list, all_invalid_events, member_key)
        summary_data[member_key]["tracker_lines"] = _build_tracker_lines(rate, last, first, valid_periods_list, all_invalid_events, member_key)

        first_sheet = member_data.get("sheets", [{}])[0]
        src_file = os.path.join(DATA_DIR, first_sheet.get("source_file", ""))

        if not os.path.exists(src_file):
            log(f"⚠️ TORIS REBUILD SKIP → Source file not found: {src_file}")
            continue

        toris_name = f"{rate}_{last}_{first}__TORIS_SEA_DUTY_CERT_SHEETS.pdf".replace(" ", "_")
        toris_path = os.path.join(TORIS_CERT_FOLDER, toris_name)

        if os.path.exists(toris_path):
            os.remove(toris_path)

        computed_days = sum(p["days"] for p in valid_periods_list)

        mark_sheet_with_strikeouts(
            src_file,
            [],
            all_invalid_events,
            toris_path,
            None,
            computed_days,
            override_valid_rows=all_valid_rows,
        )

        _apply_toris_certifier(toris_path, member_key)
        toris_total += 1

    # Consolidated all missions (rebuild) (unchanged behavior + cancel support)
    if consolidate_all_missions:
        log("=== CREATING CONSOLIDATED ALL MISSIONS PG-13 FORMS (REBUILD) ===")
        from app.core.pdf_writer import make_consolidated_all_missions_pdf
    
        for member_key, member_data in summary_data.items():
    
            # 🔹 PATCH: cancel support during rebuild consolidated generation
            if _cancel_and_exit("❌ REBUILD CANCELLED DURING ALL-MISSIONS", "Cancelled by user"):
                return
    
            ship_groups = {}
            for ship, start, end in member_data.get("valid_periods", []):
                ship_groups.setdefault(ship, []).append({"start": start, "end": end})
    
            if ship_groups:
                rp = member_data.get("reporting_periods", []) or []
                overall_start, overall_end = _compute_overall_reporting_range(
                    rp,
                    context=f"rebuild {member_key}"
                )
    
                make_consolidated_all_missions_pdf(
                    ship_groups,
                    member_key,
                    overall_start=overall_start,
                    overall_end=overall_end,
                    rate=member_data.get("rate"),
                    last=member_data.get("last"),
                    first=member_data.get("first"),
                )
    
                pg13_total += 1
                log(f"Created consolidated all missions PG-13 for {member_key}")
    
        log(f"=== COMPLETED {pg13_total} CONSOLIDATED ALL MISSIONS PG-13 FORMS (REBUILD) ===")

    set_progress(percent=90, current_step="Writing summary files")
    write_summary_files(summary_data)

    set_progress(percent=95, current_step="Merging PDFs")
    _fresh_merge_package()

    set_progress(
        status="COMPLETE",
        percent=100,
        current_step="Rebuild complete",
        details={"pg13_created": pg13_total, "toris_marked": toris_total},
    )

    log("REBUILD OUTPUTS COMPLETE")


# =============================================================================
# REBUILD SINGLE MEMBER FUNCTION
# =============================================================================
def rebuild_single_member(member_key, consolidate_pg13=False, consolidate_all_missions=False):
    """
    Rebuild outputs for a SINGLE member only.
    """
    if not os.path.exists(REVIEW_JSON_PATH):
        log("REBUILD SINGLE MEMBER ERROR → REVIEW JSON NOT FOUND")
        return {"status": "error", "message": "Review JSON not found"}

    with open(REVIEW_JSON_PATH, "r", encoding="utf-8") as f:
        review_state = json.load(f)

    if member_key not in review_state:
        log(f"REBUILD SINGLE MEMBER ERROR → Member not found: {member_key}")
        return {"status": "error", "message": f"Member not found: {member_key}"}

    member_data = review_state[member_key]

    log(f"=== REBUILDING SINGLE MEMBER: {member_key} ===")

    rate = member_data["rate"]
    last = member_data["last"]
    first = member_data["first"]
    mi = member_data.get("mi") or member_data.get("middle_initial") or ""

    safe_prefix = f"{rate}_{last}_{first}".replace(" ", "_").replace(",", "_")

    log(f"  → Removing old files for {member_key}")

    if os.path.exists(SEA_PAY_PG13_FOLDER):
        for f in os.listdir(SEA_PAY_PG13_FOLDER):
            if f.startswith(safe_prefix):
                os.remove(os.path.join(SEA_PAY_PG13_FOLDER, f))
                log(f"    - Deleted old PG-13: {f}")

    if os.path.exists(TORIS_CERT_FOLDER):
        for f in os.listdir(TORIS_CERT_FOLDER):
            if f.startswith(safe_prefix):
                os.remove(os.path.join(TORIS_CERT_FOLDER, f))
                log(f"    - Deleted old TORIS: {f}")

    log("  → Collecting data from sheets")

    all_valid_rows = []
    all_invalid_events = []

    summary_data = {
        member_key: {
            "rate": rate,
            "last": last,
            "first": first,
            "mi": mi,
            "valid_periods": [],
            "invalid_events": [],
            "events_followed": [],
            "tracker_lines": [],
            "reporting_periods": [],
        }
    }

    for sheet in member_data.get("sheets", []):
        if sheet.get("reporting_period"):
            summary_data[member_key]["reporting_periods"].append({
                "start": sheet["reporting_period"].get("from"),
                "end": sheet["reporting_period"].get("to"),
            })

        all_valid_rows.extend(sheet.get("rows", []))
        all_invalid_events.extend(sheet.get("invalid_events", []))

    log(f"    - Valid rows: {len(all_valid_rows)}")
    log(f"    - Invalid events: {len(all_invalid_events)}")

    log("  → Rebuilding PG-13 forms")

    groups = group_by_ship(all_valid_rows)
    ship_groups = {}
    for g in groups:
        ship_groups.setdefault(g["ship"], []).append(g)

    pg13_count = 0

    if consolidate_all_missions:
        log("  → Creating consolidated all missions PG-13")
        from app.core.pdf_writer import make_consolidated_all_missions_pdf

        all_ships_periods = {}
        for ship, periods in ship_groups.items():
            if periods:
                all_ships_periods[ship] = periods

        if all_ships_periods:
            rp = summary_data[member_key].get("reporting_periods", []) or []
            overall_start, overall_end = _compute_overall_reporting_range(rp, context=f"single_member {member_key}")

            make_consolidated_all_missions_pdf(
                all_ships_periods,
                member_key,
                overall_start=overall_start,
                overall_end=overall_end,
                rate=rate,
                last=last,
                first=first,
            )
            pg13_count = 1
            log("    - Created consolidated all missions PG-13")
    elif consolidate_pg13:
        for ship, periods in ship_groups.items():
            if not periods:
                continue
            make_pdf_for_ship(ship, periods, f"{first} {last}", consolidate=True)
            pg13_count += 1
            log(f"    - Created consolidated PG-13: {ship}")
    else:
        for ship, periods in ship_groups.items():
            if not periods:
                continue
            make_pdf_for_ship(ship, periods, f"{first} {last}", consolidate=False)
            pg13_count += len(periods)
        log(f"    - Created {pg13_count} separate PG-13 forms")

    log(f"✅ REBUILD COMPLETE FOR {member_key}")
    return {
        "status": "success",
        "member_key": member_key,
        "pg13_count": pg13_count,
        "valid_rows": len(all_valid_rows),
        "invalid_events": len(all_invalid_events),
    }

