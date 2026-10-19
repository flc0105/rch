"""Shared persistent log locations for the three independent Client watchdogs."""

import os

from client.config.runtime_config_store import get_runtime_config_dir


def get_watchdog_log_path(filename: str) -> str:
    return os.path.join(get_runtime_config_dir(), 'logs', filename)
