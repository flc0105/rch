import os
import platform
import sys
import time

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError
from core.utils.command_output import StructuredCommandResult


class MacSystemService:
    """
    macOS 系统信息与状态采集能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def run_command_text(self, command: str, timeout: int = 15) -> str:
        try:
            result = self.owner._run_shell_command(command, timeout=timeout)
            if result.returncode != 0:
                return ''
            return (result.stdout or '').strip()
        except Exception:
            return ''

    def build_process_info(self):
        import psutil
        process = psutil.Process()
        executable_path = os.path.realpath(sys.executable)
        script_path = os.path.realpath(''.join(sys.argv))

        return {
            'hostname': platform.node(),
            'macos_version': platform.mac_ver()[0],
            'build_version': self.run_command_text('sw_vers -buildVersion'),
            'architecture': platform.machine(),
            'hardware_model': self.run_command_text('sysctl -n hw.model'),
            'cpu_brand': self.run_command_text('sysctl -n machdep.cpu.brand_string'),
            'cpu_cores': os.cpu_count(),
            'memory': f'{round(psutil.virtual_memory().total / (1024 ** 3), 2)} GB',
            'python_version': platform.python_version(),
            'process_id': os.getpid(),
            'current_user': process.username(),
            'launch_command': f'{executable_path} {script_path}',
            'process_uptime': f'{round(time.time() - process.create_time(), 2)}s',
            'cwd': os.getcwd()
        }

    def collect_system_info(self, arg=''):
        try:
            payload = self.owner._run_checked(self.build_process_info)
            return StructuredCommandResult(
                status=1,
                data=payload,
                shape='dict',
                width=20,
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to collect system information: {e}'

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