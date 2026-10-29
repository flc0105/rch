"""Environment cleanup for child Client launches, without supervisor imports."""

import os
from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV

PROCESS_RECOVERY_WATCHDOG_SESSION_ENV = 'RCH_PROCESS_RECOVERY_WATCHDOG_SESSION'
PROCESS_RECOVERY_WATCHDOG_PID_ENV = 'RCH_PROCESS_RECOVERY_WATCHDOG_PID'
PROCESS_RECOVERY_WATCHDOG_STARTED_ENV = 'RCH_PROCESS_RECOVERY_WATCHDOG_STARTED'
PROCESS_RECOVERY_WATCHDOG_ENV_KEYS = (
    PROCESS_RECOVERY_WATCHDOG_SESSION_ENV, PROCESS_RECOVERY_WATCHDOG_PID_ENV, PROCESS_RECOVERY_WATCHDOG_STARTED_ENV,
)


def without_process_recovery_watchdog_environment(source=None):
    env = dict(os.environ if source is None else source)
    for key in (*PROCESS_RECOVERY_WATCHDOG_ENV_KEYS, RECOVERY_SOURCE_ENV):
        env.pop(key, None)
    return env
