from core.utils.command_output import StructuredCommandResult
from core.utils.decorator import desc


class CommandWatchdogMixin:
    @desc('Show watchdog runtime status', group='session')
    def watchdog(self, arg=''):
        guard_manager = getattr(self.socket, 'guard_manager', None)
        if guard_manager is None:
            return 0, 'Guard manager unavailable'

        try:
            payload = guard_manager.get_watchdog_status_payload()
            return StructuredCommandResult(status=1, data=payload, shape='dict', width=30)
        except Exception as e:
            return 0, f'Failed to get watchdog status: {e}'