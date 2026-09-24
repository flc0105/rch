import os
import time

from client.external_tools.common import ExternalToolCommon
from client.external_tools.launcher import apply_external_tool_launcher
from core.external_tools.processes import run_foreground_process


class ExternalToolOneshot(ExternalToolCommon):
    """One-shot external tool execution operations."""

    def run_foreground(self, runtime: dict, timeout_sec=None, launcher=None, launcher_override=None) -> dict:
        cwd = self.expand_path(runtime.get('cwd') or os.getcwd())
        if not os.path.isdir(cwd):
            raise FileNotFoundError(f'external tool cwd does not exist: {cwd}')

        argv = self.render_path_list(runtime.get('argv') or [])
        if not argv:
            raise ValueError('runtime.argv is required')
        argv = [
            self.expand_path(item)
            if self.should_expand_argv_item(item, index)
            else item
            for index, item in enumerate(argv)
        ]
        self.chmod(argv[0])
        argv = apply_external_tool_launcher(
            argv,
            launcher,
            launcher_override=launcher_override,
        )

        try:
            timeout_value = None if timeout_sec in ('', None) else float(timeout_sec)
        except Exception:
            raise ValueError(f'invalid oneshot timeout_sec: {timeout_sec}')
        if timeout_value is not None and timeout_value <= 0:
            raise ValueError(f'invalid oneshot timeout_sec: {timeout_sec}')

        result = run_foreground_process(
            {
                'argv': argv,
                'cwd': cwd,
                'stdout': runtime.get('stdout') or os.path.join(cwd, 'stdout.log'),
            },
            timeout_sec=timeout_value,
        )
        result.update({'argv': argv, 'cwd': cwd})
        return result

    def oneshot_payload(self, payload: dict) -> dict:
        if str(payload.get('execution') or payload.get('action') or '').strip().lower() not in ('oneshot',):
            raise ValueError('external tool payload execution must be oneshot')

        self.validate_package_payload(payload, 'oneshot')
        runtime = payload.get('runtime') or {}
        if payload.get('install_if_needed', True):
            package_info = self.download_package(payload)
            install_info = self.install_if_needed(payload, package_info)
        else:
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
        timeout_sec = payload.get('timeout_sec') or (payload.get('runtime') or {}).get('timeout_sec')
        run_result = self.run_foreground(
            runtime,
            timeout_sec=timeout_sec,
            launcher=payload.get('launcher'),
            launcher_override=payload.get('launcher_override'),
        )
        success = run_result.get('returncode') == 0 and not run_result.get('timed_out')

        return {
            'tool_id': payload.get('tool_id') or '',
            'package_id': payload.get('package_id') or '',
            'module_id': payload.get('module_id') or '',
            'display_name': payload.get('display_name') or payload.get('tool_id') or '',
            'execution': 'oneshot',
            'side': payload.get('side') or 'client',
            'platform': payload.get('platform') or '',
            'arch': payload.get('arch') or '',
            'package_key': payload.get('package_key') or '',
            'run_id': payload.get('run_id') or '',
            'status': 'completed' if success else 'failed',
            'success': success,
            'running': False,
            'returncode': run_result.get('returncode'),
            'stdout': run_result.get('stdout') or '',
            'stderr': run_result.get('stderr') or '',
            'timed_out': bool(run_result.get('timed_out')),
            'started_at': run_result.get('started_at') or '',
            'finished_at': run_result.get('finished_at') or '',
            'duration_sec': run_result.get('duration_sec'),
            'install': install_info,
            'config': config_info,
            'runtime': {**runtime, 'argv': run_result.get('argv') or runtime.get('argv') or [], 'cwd': run_result.get('cwd') or runtime.get('cwd') or ''},
            'params': payload.get('params') or {},
            'message': (
                f'{payload.get("display_name") or payload.get("tool_id") or "external tool"} completed on client'
                if success
                else f'{payload.get("display_name") or payload.get("tool_id") or "external tool"} failed on client'
            ),
        }
