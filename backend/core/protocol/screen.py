SCREEN_MIN_FPS = 1
SCREEN_MAX_FPS = 30
SCREEN_DEFAULT_FPS = 15
SCREEN_MIN_QUALITY = 20
SCREEN_MAX_QUALITY = 95
SCREEN_DEFAULT_QUALITY = 60
SCREEN_DEFAULT_CONTROL_ENABLED = True


def normalize_screen_fps(value) -> int:
    try:
        normalized = int(value)
    except Exception:
        normalized = SCREEN_DEFAULT_FPS
    return max(SCREEN_MIN_FPS, min(SCREEN_MAX_FPS, normalized))


def normalize_screen_quality(value) -> int:
    try:
        normalized = int(value)
    except Exception:
        normalized = SCREEN_DEFAULT_QUALITY
    return max(SCREEN_MIN_QUALITY, min(SCREEN_MAX_QUALITY, normalized))
