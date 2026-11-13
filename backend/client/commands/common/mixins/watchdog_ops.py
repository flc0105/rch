from core.utils.command_output import StructuredCommandResult
from core.utils.decorator import desc
from client.watchdog.control import get_watchdog_status


class CommandWatchdogMixin:
    @desc('Show watchdog runtime status', group='runtime')
    def watchdog(self, arg=''):
        try:
            return StructuredCommandResult(status=1, data=get_watchdog_status(self.socket), shape='grouped_dict')
        except Exception as e:
            return 0, f'Failed to get watchdog status: {e}'
