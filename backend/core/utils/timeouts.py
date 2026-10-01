def normalize_positive_timeout(value) -> float | None:
    if value in (None, ''):
        return None
    try:
        normalized = float(value)
    except Exception:
        return None
    return normalized if normalized > 0 else None
