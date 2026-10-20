from core.utils.command_output import StructuredCommandResult
from core.utils.decorator import desc
from client.watchdog.process_watchdog import get_process_watchdog_status_payload


class CommandWatchdogMixin:
    @desc('Show watchdog runtime status', group='runtime')
    def watchdog(self, arg=''):
        guard_manager = getattr(self.socket, 'guard_manager', None)
        if guard_manager is None:
            return 0, 'Guard manager unavailable'

        try:
            payload = guard_manager.get_watchdog_status_payload()
            payload['process_watchdog'] = get_process_watchdog_status_payload(
                getattr(self.socket, 'process_watchdog_manager', None)
            )
            return StructuredCommandResult(status=1, data=payload, shape='grouped_dict')
        except Exception as e:
            return 0, f'Failed to get watchdog status: {e}'