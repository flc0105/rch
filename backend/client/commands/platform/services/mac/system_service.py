import os
import platform
import time

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError
from client.runtime.client_util import get_executable_path
from core.utils.command_output import StructuredCommandResult, render_structured_result


class MacSystemService:
    """
    macOS 系统信息与状态采集能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def acmd_launchd(self, args_dict, payload=None):
        from client.runtime.sdk import launchd

        action = str(args_dict.get('action') or '').strip().lower()
        kind = str(args_dict.get('kind') or '').strip().lower()
        no_confirm = bool(args_dict.get('no-confirm'))
        output_json = bool(args_dict.get('json', False))
        if action and action not in launchd.VALID_LAUNCHD_ACTIONS:
            return 0, f'Invalid launchd action: {action} (install, start, stop, restart, uninstall, status)'
        if kind and kind not in ('agent', 'daemon'):
            return 0, f'Invalid launchd kind: {kind} (agent, daemon)'
        if no_confirm and (not action or not kind):
            return 0, '--no-confirm requires both action and kind'

        if not no_confirm:
            # This import and every Broker request are bypassed for --no-confirm.
            from client.commands.common.services.interaction_service import (
                CommandInteractions, CommandInteractionError,
            )
            self.owner._set_timeout(300)
            ui = CommandInteractions(self.owner)
            try:
                if not action:
                    action = ui.select('Choose the launchd action:',
                                       ['install', 'start', 'stop', 'restart', 'uninstall', 'status'],
                                       title='Launchd action')
                if not kind:
                    kind = ui.select('Choose the launchd service type:',
                                     ['agent', 'daemon'], title='Launchd type')

                preview = {
                    'summary': [
                        {'label': 'Action', 'value': action},
                        {'label': 'Type', 'value': 'LaunchAgent' if kind == 'agent' else 'LaunchDaemon'},
                        {'label': 'Label', 'value': args_dict['label']},
                        {'label': 'KeepAlive', 'value': str(args_dict['keep_alive']).lower()},
                        {'label': 'RunAtLoad', 'value': str(args_dict['run_at_load']).lower()},
                    ],
                    'notice': ('KeepAlive and RunAtLoad apply when installing. '
                               'Stopping or uninstalling the running Client may disconnect this session.'),
                }
                if kind == 'agent':
                    preview['summary'].extend([
                        {'label': 'Scope', 'value': args_dict['scope']},
                        {'label': 'Target user', 'value': args_dict['target_user'] or 'Current GUI user (automatic)'},
                    ])
                if not ui.approve_preview('Approve this launchd operation?', preview,
                                          title='Review launchd operation'):
                    return 0, 'launchd action not approved; no changes made'
            except CommandInteractionError as exc:
                return 0, f'launchd interaction cancelled or unavailable: {exc}'

        try:
            self.owner._checkpoint(fallback_timeout=300)
            result = launchd.manage(
                kind=kind,
                action=action,
                label=args_dict['label'],
                scope=args_dict['scope'] if kind == 'agent' else 'user',
                target_user=(args_dict['target_user'] or None) if kind == 'agent' else None,
                keep_alive=args_dict['keep_alive'],
                run_at_load=args_dict['run_at_load'],
            )
            status = 1 if result.get('ok') else 0
            structured = StructuredCommandResult(
                status=status,
                data=result,
                shape='dict',
                width=20,
            )
            if output_json:
                return render_structured_result(structured, output_format='json')
            return status, launchd.format_result(result)
        except (ValueError, OSError, RuntimeError) as exc:
            return 0, f'launchd {action or "operation"} failed: {exc}'

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
            'launch_command': get_executable_path(),
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