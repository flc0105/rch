"""One-shot startup provenance for a Client revived by a Local Heartbeat Watchdog."""

import os

RECOVERY_SOURCE_ENV = 'RCH_CLIENT_RECOVERY_SOURCE'
LOCAL_HEARTBEAT_WATCHDOG = 'local_heartbeat_watchdog'
PROCESS_RECOVERY_WATCHDOG = 'process_recovery_watchdog'
_RECOVERY_SOURCES = {LOCAL_HEARTBEAT_WATCHDOG, PROCESS_RECOVERY_WATCHDOG}


def consume_recovery_source():
    """Read once on Client startup, not on subsequent network reconnects."""
    value = os.environ.pop(RECOVERY_SOURCE_ENV, '')
    return value if value in _RECOVERY_SOURCES else ''
