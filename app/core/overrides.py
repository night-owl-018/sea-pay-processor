import os
import json
from datetime import datetime
from app.core.config import OVERRIDES_DIR


def _override_path(member_key):
    """
    Convert 'STG1 NIVERA,RYAN' → 'STG1_NIVERA_RYAN.json'
    """
    safe = member_key.replace(" ", "_").replace(",", "_")
    return os.path.join(OVERRIDES_DIR, f"{safe}.json")


def _make_event_signature(event):
    """
    Create a unique signature for an event based on its core content.
    This signature remains stable even when event moves between arrays.
    """
    date = str(event.get("date", ""))
    ship = str(event.get("ship", ""))
    raw = str(event.get("raw", ""))
    occ_idx = str(event.get("occ_idx", ""))
    
    return f"{date}|{ship}|{occ_idx}|{raw}"


# -----------------------------------------------------------
# LOAD OVERRIDES FOR ONE MEMBER
# -----------------------------------------------------------
def load_overrides(member_key):
    path = _override_path(member_key)
    if not os.path.exists(path):
        return {"overrides": []}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"overrides": []}


# -----------------------------------------------------------
# SAVE OVERRIDE ENTRY
# -----------------------------------------------------------
def save_override(member_key, sheet_file, event_index, status, reason, source):
    """
    Save or update an override entry.
    Replaces any existing override for the same event.
    """
    data = load_overrides(member_key)

    new_override = {
        "sheet_file": sheet_file,
        "event_index": event_index,
        "override_status": status,
        "override_reason": reason,
        "source": source,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    # Remove any existing override for this event
    data["overrides"] = [
        ov for ov in data.get("overrides", [])
        if not (ov.get("sheet_file") == sheet_file and ov.get("event_index") == event_index)
    ]

    data["overrides"].append(new_override)

    os.makedirs(OVERRIDES_DIR, exist_ok=True)
    with open(_override_path(member_key), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# -----------------------------------------------------------
# CLEAR OVERRIDES FOR A MEMBER
# -----------------------------------------------------------
def clear_overrides(member_key):
    path = _override_path(member_key)
    if os.path.exists(path):
        os.remove(path)


# -----------------------------------------------------------
# APPLY OVERRIDES DURING REVIEW MERGE
# -----------------------------------------------------------
def apply_overrides(member_key, review_state_member):
    """
    Apply overrides by matching events based on their content signature.
    
    CRITICAL FIX: Build signature maps FIRST, then find events by signature
    regardless of their current location (valid or invalid array).
    """

    overrides = load_overrides(member_key).get("overrides", [])
    if not overrides:
        return review_state_member

    for sheet in review_state_member.get("sheets", []):
        sheet_file = sheet.get("source_file")
        
        # Filter overrides for this sheet
        sheet_overrides = [ov for ov in overrides if ov.get("sheet_file") == sheet_file]
        if not sheet_overrides:
            continue

        valid_rows = sheet.get("rows", [])
        invalid_events = sheet.get("invalid_events", [])
        
        # STEP 1: Build signature maps for ALL events in BOTH arrays
        # This lets us find events regardless of where they currently are
        all_events = {}  # signature -> (event, location, index)
        
        for idx, row in enumerate(valid_rows):
            sig = _make_event_signature(row)
            all_events[sig] = (row, "valid", idx)
        
        for idx, event in enumerate(invalid_events):
            sig = _make_event_signature(event)
            all_events[sig] = (event, "invalid", idx)
        
        # STEP 2: For each override, find the event by its ORIGINAL position first,
        # then use signature to track it if it moved
        moves_to_invalid = []  # (current_idx, new_invalid_entry)
        moves_to_valid = []    # (current_idx, new_valid_entry)
        
        for ov in sheet_overrides:
            original_idx = ov["event_index"]
            status = ov["override_status"]
            reason = ov["override_reason"]
            source = ov.get("source")

            # Try to find event at original position
            target_event = None
            current_location = None
            current_idx = None
            event_sig = None

            # Check original position first
            if original_idx >= 0 and original_idx < len(valid_rows):
                target_event = valid_rows[original_idx]
                current_location = "valid"
                current_idx = original_idx
                event_sig = _make_event_signature(target_event)
            elif original_idx < 0:
                invalid_index = -original_idx - 1
                if invalid_index < len(invalid_events):
                    target_event = invalid_events[invalid_index]
                    current_location = "invalid"
                    current_idx = invalid_index
                    event_sig = _make_event_signature(target_event)

            # CRITICAL: If not at original position, search by signature across ALL events
            if target_event is None or event_sig is None:
                # Event has moved or doesn't exist - skip this override
                continue
            
            # Check if event moved by looking it up in signature map
            if event_sig in all_events:
                # Event found - update its current location
                target_event, current_location, current_idx = all_events[event_sig]
            else:
                # Event not found anywhere - skip
                continue

            # STEP 3: Apply the override based on current location and desired status
            if current_location == "valid":
                if status == "invalid":
                    # Move valid → invalid
                    new_invalid = dict(target_event)
                    new_invalid.update({
                        "reason": reason or "Forced invalid by override",
                        "category": "override",
                        "source": "override",
                        "override": {
                            "status": status,
                            "reason": reason,
                            "source": source,
                            "history": target_event.get("override", {}).get("history", []),
                        },
                        "final_classification": {
                            "is_valid": False,
                            "reason": reason,
                            "source": "override",
                        },
                        "status": "invalid",
                        "status_reason": reason,
                    })
                    moves_to_invalid.append((current_idx, new_invalid))
                else:
                    # Update in place (keeping as valid)
                    if "override" not in target_event:
                        target_event["override"] = {}
                    target_event["override"].update({
                        "status": status,
                        "reason": reason,
                        "source": source,
                    })
                    if "final_classification" not in target_event:
                        target_event["final_classification"] = {}
                    target_event["final_classification"].update({
                        "is_valid": True,
                        "reason": reason,
                        "source": "override",
                    })
                    if "status" in target_event:
                        target_event["status"] = status or "valid"
                        target_event["status_reason"] = reason

            else:  # Currently in invalid
                if status == "valid":
                    # Move invalid → valid
                    new_row = dict(target_event)
                    new_row.update({
                        "status": "valid",
                        "status_reason": reason,
                        "override": {
                            "status": status,
                            "reason": reason,
                            "source": source,
                            "history": target_event.get("override", {}).get("history", []),
                        },
                        "final_classification": {
                            "is_valid": True,
                            "reason": reason,
                            "source": "override",
                        },
                    })
                    
                    # Ensure required fields exist
                    for field, default in [("is_inport", False), ("inport_label", None), 
                                          ("is_mission", False), ("label", None), ("confidence", 1.0)]:
                        if field not in new_row:
                            new_row[field] = default
                    
                    moves_to_valid.append((current_idx, new_row))
                else:
                    # Update in place (keeping as invalid)
                    if "override" not in target_event:
                        target_event["override"] = {}
                    target_event["override"].update({
                        "status": status,
                        "reason": reason,
                        "source": source,
                    })
                    if "final_classification" not in target_event:
                        target_event["final_classification"] = {}
                    target_event["final_classification"].update({
                        "is_valid": False,
                        "reason": reason,
                        "source": "override",
                    })

        # STEP 4: Execute moves (highest index first to avoid shifting)
        moves_to_invalid.sort(reverse=True, key=lambda x: x[0])
        for idx, new_invalid in moves_to_invalid:
            invalid_events.append(new_invalid)
            valid_rows.pop(idx)

        moves_to_valid.sort(reverse=True, key=lambda x: x[0])
        for idx, new_row in moves_to_valid:
            valid_rows.append(new_row)
            invalid_events.pop(idx)

        # Update sheet
        sheet["rows"] = valid_rows
        sheet["invalid_events"] = invalid_events

    return review_state_member
