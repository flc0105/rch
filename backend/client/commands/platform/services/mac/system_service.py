from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


class MacSystemService:
    """
    macOS 系统信息与状态采集能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def get_idle_time(self):
        try:
            from Quartz import (
                CGEventSourceSecondsSinceLastEventType,
                kCGAnyInputEventType,
                kCGEventSourceStateHIDSystemState,
            )

            idle_seconds = self.owner._run_checked(
                CGEventSourceSecondsSinceLastEventType,
                kCGEventSourceStateHIDSystemState,
                kCGAnyInputEventType,
            )
            return 1, f'User idle time: {idle_seconds:.2f} seconds'
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to read idle time: {e}'