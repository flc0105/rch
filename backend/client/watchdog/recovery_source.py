"""One-shot startup provenance for a Client revived by a local watchdog."""

import os

RECOVERY_SOURCE_ENV = 'RCH_CLIENT_RECOVERY_SOURCE'
LOCAL_WATCHDOG = 'local_watchdog'
PROCESS_WATCHDOG = 'process_watchdog'
_RECOVERY_SOURCES = {LOCAL_WATCHDOG, PROCESS_WATCHDOG}


def consume_recovery_source():
    """Read once on Client startup, not on subsequent network reconnects."""
    value = os.environ.pop(RECOVERY_SOURCE_ENV, '')
    return value if value in _RECOVERY_SOURCES else ''
