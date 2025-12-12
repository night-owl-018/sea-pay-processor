from collections import deque
from datetime import datetime

# ------------------------------------------------
# LIVE LOG BUFFER
# ------------------------------------------------

LIVE_LOGS = deque(maxlen=500)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LIVE_LOGS.append(line)


def clear_logs():
    LIVE_LOGS.clear()
    print("Logs cleared", flush=True)


# ------------------------------------------------
# PROGRESS STATE FOR UI
# ------------------------------------------------

PROGRESS = {
    "status": "idle",           # idle | processing | complete | error
    "total_files": 0,
    "current_file": 0,
    "current_step": "",
    "percentage": 0,
    "details": {},
}


def reset_progress():
    PROGRESS.update(
        {
            "total_files": 0,
            "current_file": 0,
            "current_step": "",
            "percentage": 0,
            "details": {},
        }
    )


def set_progress(**kwargs):
    PROGRESS.update(kwargs)


def get_progress():
    return PROGRESS


# ------------------------------------------------
# ✅ REQUIRED FOR processing.py
# ------------------------------------------------

def add_progress_detail(key: str, value):
    """
    Safely update PROGRESS['details']
    """
    if "details" not in PROGRESS:
        PROGRESS["details"] = {}
    PROGRESS["details"][key] = value
