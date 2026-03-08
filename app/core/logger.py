import os
import threading
from datetime import datetime

from app.core.config import LOG_PATH, MASK_LOG_PATHS

_LOCK = threading.Lock()
_LOGS = []
_PROGRESS = {
    "status": "IDLE",
    "percent": 0,
    "current_step": "",
    "details": {},
}
_MAX_LOG_LINES = 2000

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def _safe_message(message: str) -> str:
    line = str(message)
    if MASK_LOG_PATHS:
        line = line.replace("/app/", "[app]/")
    return line

def log(message: str) -> None:
    if message is None:
        return
    line = _safe_message(message)
    if not line.startswith("["):
        line = f"[{_ts()}] {line}"
    with _LOCK:
        _LOGS.append(line)
        if len(_LOGS) > _MAX_LOG_LINES:
            del _LOGS[: len(_LOGS) - _MAX_LOG_LINES]
    try:
        if LOG_PATH:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass

def clear_logs() -> None:
    with _LOCK:
        _LOGS.clear()

def get_logs() -> list[str]:
    with _LOCK:
        return list(_LOGS)

def reset_progress() -> None:
    with _LOCK:
        _PROGRESS["status"] = "IDLE"
        _PROGRESS["percent"] = 0
        _PROGRESS["current_step"] = ""
        _PROGRESS["details"] = {}

def set_progress(**kwargs) -> None:
    with _LOCK:
        if "status" in kwargs and kwargs["status"] is not None:
            _PROGRESS["status"] = str(kwargs["status"]).upper()
        if "current_step" in kwargs and kwargs["current_step"] is not None:
            _PROGRESS["current_step"] = str(kwargs["current_step"])
        if "details" in kwargs and isinstance(kwargs["details"], dict):
            _PROGRESS.setdefault("details", {})
            _PROGRESS["details"].update(kwargs["details"])
        pct = None
        if "percent" in kwargs and kwargs["percent"] is not None:
            pct = kwargs["percent"]
        elif "percentage" in kwargs and kwargs["percentage"] is not None:
            pct = kwargs["percentage"]
        if pct is None:
            try:
                tf = kwargs.get("total_files")
                cf = kwargs.get("current_file")
                if tf is not None and cf is not None and int(tf) > 0:
                    pct = int((int(cf) / int(tf)) * 100)
            except Exception:
                pct = None
        if pct is not None:
            try:
                pct_i = int(pct)
            except Exception:
                pct_i = 0
            _PROGRESS["percent"] = max(0, min(100, pct_i))

def add_progress_detail(key: str, amount: int = 1) -> None:
    if not key:
        return
    try:
        delta = int(amount)
    except Exception:
        delta = 0
    with _LOCK:
        _PROGRESS.setdefault("details", {})
        cur = _PROGRESS["details"].get(key, 0)
        try:
            cur_i = int(cur)
        except Exception:
            cur_i = 0
        _PROGRESS["details"][key] = cur_i + delta

def get_progress() -> dict:
    with _LOCK:
        return {
            "status": _PROGRESS.get("status", "IDLE"),
            "percent": int(_PROGRESS.get("percent", 0) or 0),
            "current_step": _PROGRESS.get("current_step", ""),
            "details": dict(_PROGRESS.get("details", {}) or {}),
            "log": list(_LOGS),
        }
