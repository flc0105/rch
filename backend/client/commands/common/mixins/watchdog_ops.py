from core.utils.command_output import StructuredCommandResult
from core.utils.decorator import desc


class CommandWatchdogMixin:
    @desc('Show watchdog runtime status', group='runtime')
    def watchdog(self, arg=''):
        from client.watchdog.watchdog_status import inactive_guard_status, inactive_process_status

        guard_manager = getattr(self.socket, 'guard_manager', None)
        manager = getattr(self.socket, 'process_watchdog_manager', None)
        try:
            if guard_manager is not None:
                payload = guard_manager.get_watchdog_status_payload()
            else:
                payload = inactive_guard_status(getattr(self.socket, 'client_id', ''))

            if manager is not None or (guard_manager is not None and not hasattr(self.socket, 'runtime')):
                # Direct GuardManager diagnostic callers retain existing runtime_config status.
                from client.watchdog.process_watchdog import get_process_watchdog_status_payload
                payload['process_watchdog'] = get_process_watchdog_status_payload(manager)
            else:
                payload['process_watchdog'] = inactive_process_status()
            return StructuredCommandResult(status=1, data=payload, shape='grouped_dict')
        except Exception as e:
            return 0, f'Failed to get watchdog status: {e}'
