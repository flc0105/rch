"""Windows UAC elevation and elevated Client launching."""


# ShellExecuteW can request UAC elevation but cannot set CreateProcess flags.
# Run this short Python helper after authorization; it reports the actual child
# PID (or the launch error) through a local file rather than assuming success.
_ELEVATED_DETACHED_HELPER = r'''
import base64
import json
import os
import subprocess
import sys
import time
import traceback

request = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
status_path = request['status_path']
log_path = request['log_path']

def report(result):
    pending = status_path + '.tmp'
    with open(pending, 'w', encoding='utf-8') as stream:
        json.dump(result, stream)
    os.replace(pending, status_path)

try:
    env = os.environ.copy()
    for key in request['clear_env']:
        env.pop(key, None)
    with open(log_path, 'ab') as errors:
        child = subprocess.Popen(
            request['argv'], cwd=request['cwd'], env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
            close_fds=True, shell=False,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        time.sleep(0.4)
        exit_code = child.poll()
        if exit_code is not None:
            raise RuntimeError('Client exited immediately with code: ' + str(exit_code))
    report({'ok': True, 'pid': child.pid})
except Exception as exc:
    try:
        with open(log_path, 'a', encoding='utf-8') as errors:
            traceback.print_exc(file=errors)
    except OSError:
        pass
    report({'ok': False, 'error': str(exc)})
'''


class WinPrivilegeService:
    """Windows 提权/管理员执行能力。"""

    DETACHED_RESULT_TIMEOUT_SECONDS = 12

    def __init__(self, owner):
        self.owner = owner

    def run_as_admin(self, command):
        import ctypes
        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                'runas',
                'cmd.exe',
                f'/c {command}',
                None,
                1,
            )
            if result > 32:
                return 1, f'Executed: {command}'
            return 0, f'Failed with code: {result}'
        except Exception as e:
            return 0, f'Failed: {e}'

    @staticmethod
    def _detached_launch_arguments(status_path, log_path):
        """Use an elevated Python host to start the real Client detached."""
        import base64
        import json
        import os
        import subprocess

        from client.runtime.client_util import (
            _resolve_python_command_for_source_bundle,
            get_executable_argv,
        )
        from client.watchdog.watchdog_environment import PROCESS_RECOVERY_WATCHDOG_ENV_KEYS
        from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV

        python_command = _resolve_python_command_for_source_bundle()
        request = {
            'argv': get_executable_argv(),
            'cwd': os.getcwd(),
            'status_path': status_path,
            'log_path': log_path,
            'clear_env': [*PROCESS_RECOVERY_WATCHDOG_ENV_KEYS, RECOVERY_SOURCE_ENV],
        }
        request_arg = base64.b64encode(
            json.dumps(request, ensure_ascii=False).encode('utf-8')
        ).decode('ascii')
        parameters = subprocess.list2cmdline(
            python_command[1:] + ['-c', _ELEVATED_DETACHED_HELPER, request_arg]
        )
        return python_command[0], parameters

    def _wait_for_detached_launch_status(self, status_path):
        import json
        import os
        import time

        deadline = time.monotonic() + self.DETACHED_RESULT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if os.path.isfile(status_path):
                with open(status_path, 'r', encoding='utf-8') as stream:
                    return json.load(stream)
            time.sleep(0.1)
        return {'ok': False, 'error': 'Elevated Python helper did not return a launch result'}

    def spawn_elevated_instance(self, *, detached=False):
        """Request UAC and report the real detached Client launch result."""
        import ctypes
        import os
        import shutil
        import tempfile
        from client.runtime.client_util import get_exec_and_args
        from client.runtime.temp_workspace import get_temp_category_dir

        work_dir = ''
        try:
            if detached:
                work_dir = tempfile.mkdtemp(
                    prefix='client_elevation_',
                    dir=get_temp_category_dir('client_logs', private=True),
                )
                status_path = os.path.join(work_dir, 'launch-status.json')
                log_path = os.path.join(work_dir, 'spawn.log')
                executable, parameters = self._detached_launch_arguments(status_path, log_path)
            else:
                executable, parameters = get_exec_and_args()

            result = ctypes.windll.shell32.ShellExecuteW(
                None, 'runas', executable, parameters, os.getcwd(), 0 if detached else 1,
            )
            if result <= 32:
                if work_dir:
                    shutil.rmtree(work_dir, ignore_errors=True)
                return 0, f'Elevated Client launch failed (ShellExecuteW: {result})'
            if not detached:
                return 1, 'Elevated Client launch requested'

            status = self._wait_for_detached_launch_status(status_path)
            if status.get('ok') and int(status.get('pid') or 0) > 0:
                return 1, f'Elevated detached Client started, PID: {status["pid"]}. Startup log: {log_path}'
            detail = str(status.get('error') or 'No child PID reported')
            return 0, f'Elevated detached Client launch failed: {detail}. Startup log: {log_path}'
        except Exception as exc:
            return 0, f'Elevated Client launch failed: {exc}'
