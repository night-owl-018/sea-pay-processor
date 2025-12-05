import re
from datetime import datetime

def extract_reporting_period(text, filename=""):
    """
    Extracts the official sheet header date range:
    Example:
        "From: 8/4/2025 To: 11/24/2025"
    Returns:
        (start_date, end_date, "8/4/2025 - 11/24/2025")
    """

    # Look for "From: <date> To: <date>"
    pattern = r"From:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*To:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})"
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        from_raw = match.group(1)
        to_raw = match.group(2)

        try:
            start = datetime.strptime(from_raw, "%m/%d/%Y")
            end = datetime.strptime(to_raw, "%m/%d/%Y")
        except:
            return None, None, ""

        return start, end, f"{from_raw} - {to_raw}"

    # If OCR misses the header, attempt recovery from filename:
    # Example filename: HATTEN Sea Pay 8_4_2025 - 11_24_2025.pdf
    alt_pattern = r"(\d{1,2}_\d{1,2}_\d{4})\s*-\s*(\d{1,2}_\d{1,2}_\d{4})"
    m2 = re.search(alt_pattern, filename)

    if m2:
        try:
            s = datetime.strptime(m2.group(1).replace("_", "/"), "%m/%d/%Y")
            e = datetime.strptime(m2.group(2).replace("_", "/"), "%m/%d/%Y")
            return s, e, f"{m2.group(1)} - {m2.group(2)}"
        except:
            return None, None, ""

    return None, None, ""
