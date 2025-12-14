import time
from collections import deque
from threading import Lock

# ==============================
# INTERNAL STATE (UNCHANGED)
# ==============================

LIVE_LOGS = deque(maxlen=2000)

PROGRESS = {
    "status": "idle",
    "percentage": 0,
    "current_step": "",
    "details": [],
}

_LOCK = Lock()


# ==============================
# LOGGING (UNCHANGED)
# ==============================

def log(message: str):
    ts = time.strftime("[%H:%M:%S]")
    line = f"{ts} {message}"

    print(line, flush=True)

    with _LOCK:
        LIVE_LOGS.append(line)


def clear_logs():
    with _LOCK:
        LIVE_LOGS.clear()


# ==============================
# PROGRESS (UNCHANGED)
# ==============================

def reset_progress():
    with _LOCK:
        PROGRESS["status"] = "idle"
        PROGRESS["percentage"] = 0
        PROGRESS["current_step"] = ""
        PROGRESS["details"] = []


def set_progress(status=None, percentage=None, current_step=None):
    with _LOCK:
        if status is not None:
            PROGRESS["status"] = status
        if percentage is not None:
            PROGRESS["percentage"] = percentage
        if current_step is not None:
            PROGRESS["current_step"] = current_step


def add_progress_detail(detail: str):
    with _LOCK:
        PROGRESS["details"].append(detail)


def get_progress():
    with _LOCK:
        return {
            "status": PROGRESS["status"],
            "percentage": PROGRESS["percentage"],
            "current_step": PROGRESS["current_step"],
            "details": list(PROGRESS["details"]),
        }


# ======================================================
# 🔧 UI ADAPTER (PATCH — READ ONLY, SAFE)
# ======================================================

def get_ui_progress():
    """
    Adapter for index.html.
    Does NOT change internal logger behavior.
    """
    with _LOCK:
        return {
            "status": PROGRESS.get("status", "idle"),
            "percent": PROGRESS.get("percentage", 0),
            "log": "\n".join(LIVE_LOGS),
        }
