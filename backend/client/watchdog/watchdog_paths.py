"""Shared Client temp log locations for the three independent watchdogs."""

import os

from client.runtime.temp_workspace import get_temp_category_dir


def get_watchdog_log_path(filename: str) -> str:
    return os.path.join(get_temp_category_dir('watchdog_logs', private=True), filename)


def get_existing_watchdog_log_path(filename: str) -> str:
    """Expose a diagnostic log only after its file has actually been created."""
    path = get_watchdog_log_path(filename)
    return path if os.path.isfile(path) else ''
