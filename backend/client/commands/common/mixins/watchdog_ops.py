from core.utils.command_output import StructuredCommandResult
from core.utils.decorator import desc


class CommandWatchdogMixin:
    @desc('Show watchdog runtime status', group='runtime')
    def watchdog(self, arg=''):
        from client.watchdog.watchdog_status import inactive_watchdog_worker_status, inactive_process_recovery_watchdog_status

        watchdog_manager = getattr(self.socket, 'watchdog_manager', None)
        manager = getattr(self.socket, 'process_recovery_watchdog_manager', None)
        try:
            if watchdog_manager is not None:
                payload = watchdog_manager.get_watchdog_status_payload()
            else:
                payload = inactive_watchdog_worker_status(getattr(self.socket, 'client_id', ''))

            if manager is not None or (watchdog_manager is not None and not hasattr(self.socket, 'runtime')):
                # Direct GuardManager diagnostic callers retain existing runtime_config status.
                from client.watchdog.process_recovery_watchdog import get_process_recovery_watchdog_status_payload
                payload['process_recovery_watchdog'] = get_process_recovery_watchdog_status_payload(manager)
            else:
                payload['process_recovery_watchdog'] = inactive_process_recovery_watchdog_status()
            return StructuredCommandResult(status=1, data=payload, shape='grouped_dict')
        except Exception as e:
            return 0, f'Failed to get watchdog status: {e}'
