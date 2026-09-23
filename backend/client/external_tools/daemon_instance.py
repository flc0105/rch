import os
import shlex
import shutil
import subprocess
import time
from types import SimpleNamespace

from client.external_tools.common import ExternalToolCommon
from client.external_tools.launcher import apply_external_tool_launcher
from core.external_tools.files import tail_text_file
from core.external_tools.processes import (
    is_pid_alive,
    read_pid_file,
    signal_name_to_value,
    signal_process_group_or_pid,
    start_detached_process,
    stop_by_signal,
)


class ExternalToolDaemonInstance(ExternalToolCommon):
    """Daemon-style external tool instance lifecycle operations."""

    def build_runtime(self, payload: dict) -> dict:
        self.validate_package_payload(payload, 'start')
        runtime = payload.get('runtime') or {}
        argv = self.render_path_list(runtime.get('argv') or [])

        if not argv:
            raise ValueError('runtime.argv is required')

        argv = [
            self.expand_path(item)
            if self.should_expand_argv_item(item, index)
            else item
            for index, item in enumerate(argv)
        ]
        argv = apply_external_tool_launcher(argv, payload.get('launcher'))

        cwd = self.expand_path(runtime.get('cwd') or os.getcwd())
        stdout = self.expand_path(runtime.get('stdout') or '~/.ops/external_tools/runtime/stdout.log')
        stderr = runtime.get('stderr') or 'stdout'

        if stderr != 'stdout':
            stderr = self.expand_path(stderr)

        pid_file = self.expand_path(runtime.get('pid_file') or '~/.ops/external_tools/runtime/tool.pid')
        state_file = self.expand_path(
            runtime.get('state_file') or os.path.join(os.path.dirname(pid_file), 'state.json')
        )

        return {
            'argv': argv,
            'cwd': cwd,
            'stdout': stdout,
            'stderr': stderr,
            'pid_file': pid_file,
            'state_file': state_file,
        }

    def start_detached(self, runtime: dict):
        return start_detached_process(runtime)

    def preview_payload(self, payload: dict) -> dict:
        # 只构建目标端最终 argv/cwd，不启动进程。
        runtime = self.build_runtime(payload)
        argv = runtime.get('argv') or []
        cwd = runtime.get('cwd') or ''

        if os.name == 'nt':
            command = subprocess.list2cmdline(argv)
            shell_command = f'cd /d {subprocess.list2cmdline([cwd])} && {command}' if cwd else command
            shell = 'cmd'
        else:
            command = shlex.join(argv)
            shell_command = f'cd {shlex.quote(cwd)} && {command}' if cwd else command
            shell = 'sh'

        return {
            'tool_id': payload.get('tool_id') or '',
            'package_id': payload.get('package_id') or '',
            'module_id': payload.get('module_id') or '',
            'instance_id': payload.get('instance_id') or 'default',
            'platform': payload.get('platform') or '',
            'arch': payload.get('arch') or '',
            'shell': shell,
            'cwd': cwd,
            'argv': argv,
            'command': command,
            'shell_command': shell_command,
        }

    def start_payload(self, payload: dict) -> dict:
        runtime = self.build_runtime(payload)
        existing_pid = self.read_pid(runtime['pid_file'])

        if self.is_pid_alive(existing_pid):
            status = self.status_from_payload(payload)
            status['message'] = f'{payload.get("display_name") or payload.get("tool_id") or "external tool"} instance {payload.get("instance_id") or "default"} is already running'
            return status

        if payload.get('install_if_needed', True):
            package_info = self.download_package(payload)
            install_info = self.install_if_needed(payload, package_info)
            archive_path = install_info.get('package') or package_info.get('archive_path') or ''
        else:
            archive_path = ''
            install_info = self.install_status_payload(payload)
            if not install_info.get('installed'):
                raise ValueError('Package is not installed. Please install it first.')
            install_info.update({
                'already_installed': True,
                'extracted': False,
                'message': 'using existing installation',
            })
            self.chmod(install_info.get('executable_path') or '')

        config_info = self.write_config(payload)
        process = self.start_detached(runtime)
        state_file = self.write_state(payload, install_info, config_info, runtime, process)

        return {
            'tool_id': payload.get('tool_id') or '',
            'side': payload.get('side') or 'client',
            'instance_id': payload.get('instance_id') or 'default',
            'status': 'running',
            'running': True,
            'pid': process.pid,
            'package': archive_path,
            'install': install_info,
            'config': config_info,
            'runtime': runtime,
            'state_file': state_file,
            'message': f'{payload.get("display_name") or payload.get("tool_id") or "external tool"} instance {payload.get("instance_id") or "default"} started on client',
        }

    def read_pid(self, pid_file: str):
        return read_pid_file(pid_file)
    def is_pid_alive(self, pid) -> bool:
        return is_pid_alive(pid)
    def is_windows_pid_alive(self, pid: int) -> bool:
        return is_pid_alive(pid)
    def signal_process_group_or_pid(self, pid: int, sig: int):
        signal_process_group_or_pid(pid, sig)
    def state_file_from_payload(self, payload: dict) -> str:
        runtime = payload.get('runtime') or {}
        state_file = runtime.get('state_file')
        if state_file:
            return self.expand_path(state_file)

        pid_file = self.expand_path(runtime.get('pid_file') or '~/.ops/external_tools/runtime/tool.pid')
        return os.path.join(os.path.dirname(pid_file), 'state.json')

    def pid_file_from_payload(self, payload: dict) -> str:
        runtime = payload.get('runtime') or {}
        return self.expand_path(
            runtime.get('pid_file') or os.path.join(os.path.dirname(self.state_file_from_payload(payload)), 'tool.pid')
        )

    def stdout_from_payload(self, payload: dict) -> str:
        runtime = payload.get('runtime') or {}
        return self.expand_path(
            runtime.get('stdout') or os.path.join(os.path.dirname(self.state_file_from_payload(payload)), 'stdout.log')
        )

    def instance_runtime_dir_from_payload(self, payload: dict) -> str:
        return os.path.dirname(self.state_file_from_payload(payload))

    def status_from_payload(self, payload: dict) -> dict:
        state_file = self.state_file_from_payload(payload)
        pid_file = self.pid_file_from_payload(payload)
        stdout = self.stdout_from_payload(payload)
        state = self.read_json(state_file)

        pid = self.read_pid(pid_file)
        alive = self.is_pid_alive(pid)

        if alive:
            status = 'running'
        elif os.path.exists(pid_file):
            status = 'stale'
        elif state:
            status = state.get('last_status') or 'stopped'
        else:
            status = 'not_started'

        runtime = state.get('runtime') if isinstance(state.get('runtime'), dict) else {}

        return {
            'tool_id': payload.get('tool_id') or state.get('tool_id') or '',
            'package_id': payload.get('package_id') or state.get('package_id') or '',
            'module_id': payload.get('module_id') or state.get('module_id') or '',
            'display_name': payload.get('display_name') or state.get('display_name') or '',
            'side': payload.get('side') or state.get('side') or 'client',
            'instance_id': payload.get('instance_id') or state.get('instance_id') or 'default',
            'status': status,
            'running': alive,
            'pid': pid,
            'pid_file': pid_file,
            'state_file': state_file,
            'stdout': stdout,
            'stderr': runtime.get('stderr') or state.get('stderr') or '',
            'runtime': runtime,
            'config': state.get('config') or {},
            'params': state.get('params') or {},
            'install': state.get('install') or {},
            'argv': state.get('argv') or runtime.get('argv') or [],
            'cwd': state.get('cwd') or runtime.get('cwd') or '',
            'started_at': state.get('started_at') or '',
            'stopped_at': state.get('stopped_at') or '',
            'message': state.get('message') or '',
        }

    def write_state(
        self,
        payload: dict,
        install_info: dict,
        config_info: dict,
        runtime: dict,
        process: SimpleNamespace,
    ) -> str:
        state_file = runtime.get('state_file') or os.path.join(os.path.dirname(runtime['pid_file']), 'state.json')

        state = {
            'tool_id': payload.get('tool_id') or '',
            'package_id': payload.get('package_id') or '',
            'module_id': payload.get('module_id') or '',
            'display_name': payload.get('display_name') or payload.get('tool_id') or '',
            'version': payload.get('version') or '',
            'platform': payload.get('platform') or '',
            'arch': payload.get('arch') or '',
            'package_key': payload.get('package_key') or '',
            'side': payload.get('side') or 'client',
            'instance_id': payload.get('instance_id') or 'default',
            'instance_name': payload.get('instance_name') or payload.get('instance_id') or 'default',
            'pid': process.pid,
            'params': payload.get('params') or {},
            'install': install_info or {},
            'config': config_info or {},
            'runtime': runtime or {},
            'argv': runtime.get('argv') or [],
            'cwd': runtime.get('cwd') or '',
            'stdout': runtime.get('stdout') or '',
            'stderr': runtime.get('stderr') or '',
            'pid_file': runtime.get('pid_file') or '',
            'state_file': state_file,
            'install_dir': install_info.get('install_dir') or '',
            'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'last_status': 'running',
        }

        self.write_json(state_file, state)
        return state_file

    def signal_name_to_value(self, value) -> int:
        return signal_name_to_value(value)
    def stop_by_signal(self, pid, stop_spec: dict) -> dict:
        return stop_by_signal(pid, stop_spec, default_timeout_sec=self.DEFAULT_STOP_TIMEOUT_SEC)
    def run_stop_command(self, stop_spec: dict) -> dict:
        argv = stop_spec.get('argv') or stop_spec.get('command') or []

        if isinstance(argv, str):
            argv = shlex.split(argv)

        if not isinstance(argv, list) or not argv:
            raise ValueError('lifecycle.stop.argv is required for command stop')

        rendered = [
            self.expand_path(str(item))
            if self.should_expand_argv_item(str(item), index)
            else str(item)
            for index, item in enumerate(argv)
        ]

        timeout = int(stop_spec.get('timeout_sec') or self.DEFAULT_STOP_TIMEOUT_SEC)

        completed = subprocess.run(
            rendered,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(1, timeout),
            close_fds=True,
        )

        return {
            'type': 'command',
            'argv': rendered,
            'returncode': completed.returncode,
            'stdout': completed.stdout,
            'stderr': completed.stderr,
        }

    def stop_command(self, payload: dict) -> dict:
        lifecycle = payload.get('lifecycle') if isinstance(payload.get('lifecycle'), dict) else {}
        stop_spec = lifecycle.get('stop') if isinstance(lifecycle.get('stop'), dict) else {}

        if not stop_spec:
            stop_spec = {
                'type': 'signal',
                'signal': 'TERM',
                'timeout_sec': self.DEFAULT_STOP_TIMEOUT_SEC,
                'kill_after_timeout': True,
            }

        pid_file = self.pid_file_from_payload(payload)
        pid = self.read_pid(pid_file)

        # If the pid file exists but the process is already gone, this is a stale
        # instance. Do not try to signal it, especially on Windows where
        # os.kill(dead_pid, sig) can raise WinError 87. Just clean runtime state.
        if not pid or not self.is_pid_alive(pid):
            result = {
                'type': 'cleanup',
                'sent': False,
                'already_stopped': True,
                'message': 'process is not running; cleaned stale instance',
            }

            try:
                if os.path.exists(pid_file):
                    os.unlink(pid_file)
            except OSError:
                pass

            state_file = self.state_file_from_payload(payload)
            state = self.read_json(state_file)
            state['last_status'] = 'stopped'
            state['stopped_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            state['stop_result'] = result
            self.write_json(state_file, state)

            return result

        if str(stop_spec.get('type') or 'signal').strip().lower() == 'command':
            result = self.run_stop_command(stop_spec)
            fallback = stop_spec.get('fallback') if isinstance(stop_spec.get('fallback'), dict) else None
            if fallback and self.is_pid_alive(pid):
                result['fallback'] = self.stop_by_signal(pid, fallback)
        else:
            result = self.stop_by_signal(pid, stop_spec)

        if not self.is_pid_alive(pid):
            try:
                if os.path.exists(pid_file):
                    os.unlink(pid_file)
            except OSError:
                pass

            state_file = self.state_file_from_payload(payload)
            state = self.read_json(state_file)
            state['last_status'] = 'stopped'
            state['stopped_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            state['stop_result'] = result
            self.write_json(state_file, state)

        return result

    def stop_payload(self, payload: dict) -> dict:
        stop_result = self.stop_command(payload)
        status = self.status_from_payload(payload)
        status['stop_result'] = stop_result
        status['message'] = f'{payload.get("display_name") or payload.get("tool_id") or "external tool"} instance {payload.get("instance_id") or "default"} stop requested on client'
        return status

    def list_instances_payload(self, payload: dict) -> dict:
        tool_id, package_id, module_id = self.runtime_parts_from_payload(payload)
        runtime_root = self.expand_path('~/.ops/external_tools/runtime')
        instances_dir = os.path.join(runtime_root, package_id, module_id, 'instances') if module_id else os.path.join(runtime_root, package_id, 'instances')
        items = []

        if os.path.isdir(instances_dir):
            for name in sorted(os.listdir(instances_dir)):
                path = os.path.join(instances_dir, name)
                if not os.path.isdir(path):
                    continue

                instance_payload = {
                    'tool_id': tool_id,
                    'package_id': package_id,
                    'module_id': module_id,
                    'display_name': payload.get('display_name') or tool_id,
                    'side': 'client',
                    'instance_id': name,
                    'runtime': {
                        'pid_file': os.path.join(path, 'tool.pid'),
                        'stdout': os.path.join(path, 'stdout.log'),
                        'stderr': 'stdout',
                        'state_file': os.path.join(path, 'state.json'),
                    },
                }
                items.append(self.status_from_payload(instance_payload))

        return {'tool_id': tool_id, 'package_id': package_id, 'module_id': module_id, 'side': 'client', 'items': items}

    def read_logs_payload(self, payload: dict) -> dict:
        stdout = self.stdout_from_payload(payload)
        max_bytes = int(payload.get('max_bytes') or self.DEFAULT_LOG_TAIL_BYTES)

        content = tail_text_file(stdout, max_bytes)

        return {
            'tool_id': payload.get('tool_id') or '',
            'instance_id': payload.get('instance_id') or 'default',
            'log_file': stdout,
            'content': content,
            'max_bytes': max_bytes,
        }

    def ensure_instance_stopped(self, payload: dict) -> dict:
        status = self.status_from_payload(payload)
        if status.get('running'):
            raise ValueError('Stop this instance before modifying runtime files.')
        return status

    def remove_instance_payload(self, payload: dict) -> dict:
        status = self.ensure_instance_stopped(payload)
        runtime_dir = self.instance_runtime_dir_from_payload(payload)

        if os.path.isdir(runtime_dir):
            shutil.rmtree(runtime_dir)

        return {
            'tool_id': payload.get('tool_id') or '',
            'side': payload.get('side') or 'client',
            'instance_id': payload.get('instance_id') or 'default',
            'removed': True,
            'runtime_dir': runtime_dir,
            'previous_status': status,
            'message': f'{payload.get("display_name") or payload.get("tool_id") or "external tool"} instance {payload.get("instance_id") or "default"} runtime removed on client',
        }

    def clear_logs_payload(self, payload: dict) -> dict:
        status = self.ensure_instance_stopped(payload)
        stdout = self.stdout_from_payload(payload)

        if os.path.isfile(stdout):
            with open(stdout, 'w', encoding='utf-8'):
                pass

        return {
            'tool_id': payload.get('tool_id') or '',
            'side': payload.get('side') or 'client',
            'instance_id': payload.get('instance_id') or 'default',
            'cleared': True,
            'log_file': stdout,
            'previous_status': status,
            'message': f'{payload.get("display_name") or payload.get("tool_id") or "external tool"} instance {payload.get("instance_id") or "default"} logs cleared on client',
        }

    def has_running_instances_for_package(self, package_id: str) -> bool:
        runtime_root = self.expand_path('~/.ops/external_tools/runtime')
        package_dir = os.path.join(runtime_root, str(package_id or '').strip())

        if not os.path.isdir(package_dir):
            return False

        for module_id in os.listdir(package_dir):
            instances_dir = os.path.join(package_dir, module_id, 'instances')
            if not os.path.isdir(instances_dir):
                continue
            tool_id = f'{package_id}.{module_id}'
            for name in os.listdir(instances_dir):
                path = os.path.join(instances_dir, name)
                if not os.path.isdir(path):
                    continue
                instance_payload = {
                    'tool_id': tool_id,
                    'package_id': package_id,
                    'module_id': module_id,
                    'display_name': tool_id,
                    'side': 'client',
                    'instance_id': name,
                    'runtime': {
                        'pid_file': os.path.join(path, 'tool.pid'),
                        'stdout': os.path.join(path, 'stdout.log'),
                        'stderr': 'stdout',
                        'state_file': os.path.join(path, 'state.json'),
                    },
                }
                status = self.status_from_payload(instance_payload)
                if status.get('running'):
                    return True

        return False

    def list_instances_all_payload(self, payload: dict) -> dict:
        runtime_root = self.expand_path('~/.ops/external_tools/runtime')
        tools = payload.get('tools') or []

        tool_specs = []
        if isinstance(tools, list) and tools:
            for item in tools:
                if not isinstance(item, dict):
                    continue
                tool_id = str(item.get('tool_id') or item.get('id') or '').strip()
                if not tool_id:
                    continue
                tool_specs.append({
                    'tool_id': tool_id,
                    'package_id': item.get('package_id') or (tool_id.split('.', 1)[0] if '.' in tool_id else tool_id),
                    'module_id': item.get('module_id') or (tool_id.split('.', 1)[1] if '.' in tool_id else ''),
                    'display_name': item.get('display_name') or tool_id,
                })
        elif os.path.isdir(runtime_root):
            for name in sorted(os.listdir(runtime_root)):
                path = os.path.join(runtime_root, name)
                if os.path.isdir(path):
                    tool_specs.append({
                        'tool_id': name,
                        'display_name': name,
                    })

        items = []
        by_tool = {}

        for spec in tool_specs:
            tool_id = spec['tool_id']
            display_name = spec.get('display_name') or tool_id
            package_id = spec.get('package_id') or (tool_id.split('.', 1)[0] if '.' in tool_id else tool_id)
            module_id = spec.get('module_id') or (tool_id.split('.', 1)[1] if '.' in tool_id else '')
            instances_dir = os.path.join(runtime_root, package_id, module_id, 'instances') if module_id else os.path.join(runtime_root, package_id, 'instances')
            tool_items = []
            by_tool[tool_id] = tool_items

            if not os.path.isdir(instances_dir):
                continue

            for name in sorted(os.listdir(instances_dir)):
                path = os.path.join(instances_dir, name)
                if not os.path.isdir(path):
                    continue

                instance_payload = {
                    'tool_id': tool_id,
                    'package_id': package_id,
                    'module_id': module_id,
                    'display_name': display_name,
                    'side': 'client',
                    'instance_id': name,
                    'runtime': {
                        'pid_file': os.path.join(path, 'tool.pid'),
                        'stdout': os.path.join(path, 'stdout.log'),
                        'stderr': 'stdout',
                        'state_file': os.path.join(path, 'state.json'),
                    },
                }

                row = self.status_from_payload(instance_payload)
                tool_items.append(row)
                items.append(row)

        return {
            'side': 'client',
            'items': items,
            'by_tool': by_tool,
        }
