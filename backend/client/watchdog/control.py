from core.protocol.control import WatchdogAction


def get_watchdog_status(connection):
    from client.watchdog.watchdog_status import inactive_watchdog_worker_status, inactive_process_recovery_watchdog_status
    watchdog_manager = getattr(connection, 'watchdog_manager', None)
    manager = getattr(connection, 'process_recovery_watchdog_manager', None)
    if watchdog_manager is not None:
        payload = watchdog_manager.get_watchdog_status_payload()
    else:
        payload = inactive_watchdog_worker_status(getattr(connection, 'client_id', ''))
    if manager is not None or (watchdog_manager is not None and not hasattr(connection, 'runtime')):
        # Direct GuardManager diagnostic callers retain existing runtime_config status.
        from client.watchdog.process_recovery_watchdog import get_process_recovery_watchdog_status_payload
        payload['process_recovery_watchdog'] = get_process_recovery_watchdog_status_payload(manager)
    else:
        payload['process_recovery_watchdog'] = inactive_process_recovery_watchdog_status()
    return payload


class WatchdogControl:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, scope, action, payload):
        if action != WatchdogAction.STATUS:
            return 0, 'Unsupported watchdog Control action'
        try:
            return 1, get_watchdog_status(self.connection)
        except Exception as exc:
            return 0, f'Failed to get watchdog status: {exc}'
