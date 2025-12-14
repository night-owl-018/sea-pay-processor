import threading
from datetime import datetime

# =========================================================
# In-memory logging + progress (thread-safe)
# =========================================================

_LOCK = threading.Lock()

# Public (back-compat) containers some modules may import directly
LIVE_LOGS = []  # list[str]
PROGRESS = {
    "status": "IDLE",
    "percent": 0,
    "total": 0,
    "processed": 0,
}

def _ts() -> str:
    return datetime.now().strftime("[%H:%M:%S]")

def clear_logs():
    """Clear live logs (UI uses this at the start of /process)."""
    with _LOCK:
        LIVE_LOGS.clear()

def get_logs():
    """Return a copy of the current logs (list of lines)."""
    with _LOCK:
        return list(LIVE_LOGS)

def reset_progress():
    """Reset progress to IDLE/0. Keeps logs untouched (caller decides)."""
    with _LOCK:
        PROGRESS["status"] = "IDLE"
        PROGRESS["percent"] = 0
        PROGRESS["total"] = 0
        PROGRESS["processed"] = 0

def set_progress(status=None, percent=None, total=None, processed=None):
    """Update progress fields safely. Any arg can be omitted."""
    with _LOCK:
        if status is not None:
            PROGRESS["status"] = str(status)
        if percent is not None:
            try:
                PROGRESS["percent"] = max(0, min(100, int(percent)))
            except Exception:
                pass
        if total is not None:
            try:
                PROGRESS["total"] = max(0, int(total))
            except Exception:
                pass
        if processed is not None:
            try:
                PROGRESS["processed"] = max(0, int(processed))
            except Exception:
                pass

def get_progress():
    """Return progress dict including log lines for /progress polling."""
    with _LOCK:
        return {
            "status": PROGRESS.get("status", "IDLE"),
            "percent": PROGRESS.get("percent", 0),
            "log": list(LIVE_LOGS),
        }

def _auto_advance_from_log(msg: str):
    """
    Minimal progress updates without touching processing.py:
    - When we see 'OCR →' lines, count one processed item.
    - Map processed/total into 10..90%.
    """
    with _LOCK:
        total = int(PROGRESS.get("total") or 0)
        if total <= 0:
            return

        if "OCR \u2192" in msg or "OCR ->" in msg:
            PROGRESS["processed"] = int(PROGRESS.get("processed") or 0) + 1
            done = PROGRESS["processed"]
            # Clamp so we never hit 100 until the worker sets COMPLETE
            pct = 10 + int(80 * min(done, total) / total)
            PROGRESS["percent"] = max(PROGRESS["percent"], min(99, pct))

def log(message: str):
    """Append a message to the live log. Adds [HH:MM:SS] prefix if missing."""
    if message is None:
        return
    msg = str(message)

    # Preserve messages that already have a timestamp prefix like [01:07:28]
    if not msg.startswith("["):
        msg = f"{_ts()} {msg}"

    with _LOCK:
        LIVE_LOGS.append(msg)
        # Keep memory bounded
        if len(LIVE_LOGS) > 5000:
            del LIVE_LOGS[:1000]

    # lightweight progress heuristics
    _auto_advance_from_log(msg)
