"""Environment cleanup for child Client launches, without supervisor imports."""

import os
from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV

PROCESS_WATCHDOG_SESSION_ENV = 'RCH_PROCESS_WATCHDOG_SESSION'
PROCESS_WATCHDOG_PID_ENV = 'RCH_PROCESS_WATCHDOG_PID'
PROCESS_WATCHDOG_STARTED_ENV = 'RCH_PROCESS_WATCHDOG_STARTED'
PROCESS_WATCHDOG_ENV_KEYS = (
    PROCESS_WATCHDOG_SESSION_ENV, PROCESS_WATCHDOG_PID_ENV, PROCESS_WATCHDOG_STARTED_ENV,
)


def without_process_watchdog_environment(source=None):
    env = dict(os.environ if source is None else source)
    for key in (*PROCESS_WATCHDOG_ENV_KEYS, RECOVERY_SOURCE_ENV):
        env.pop(key, None)
    return env
