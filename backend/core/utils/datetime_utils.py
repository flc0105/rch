from datetime import datetime


def parse_iso_datetime(value: str):
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None
