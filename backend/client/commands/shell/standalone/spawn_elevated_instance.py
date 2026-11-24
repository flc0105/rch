"""Request authorization to launch a separate elevated Client."""
import base64
import ctypes
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time

from client.runtime.mac_util import escape_osascript_text
from client.commands.runtime.interrupts import timeout
from client.commands.shell.decorators import shell_command, reverse_only
from client.runtime.client_util import get_executable_path, get_runtime_root
from core.utils.decorator import confirm


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


_DETACHED_RESULT_TIMEOUT_SECONDS = 12


@shell_command('Launch a new instance with elevated privileges ([--no-confirm] skips RCH confirmation)',
               group='privilege', platforms=('mac', 'win'))
@timeout({'mac': 150})
@reverse_only('Duplicate Instance is not supported in Bind mode. Use a different profile and port to start a separate elevated instance.')
@confirm('This may show an operating system permission prompt and wait for authorization. Continue?',
         platform_messages={'win': 'This may show a Windows UAC permission prompt and wait for authorization. Continue?'},
         no_arguments=True)
def spawn_elevated_instance(self, options=''):
    if self.command_platform == 'win':
        return _spawn_elevated_win()
    return _spawn_elevated_mac()


def _spawn_elevated_mac():
    """Authorize once, start the real Client in a new session and report its PID."""
    # macOS supplies setsid(2) but does not guarantee a setsid(1) command.
    # Perl exec replaces the launcher with the Client without changing its PID.
    launcher = 'setsid() != -1 or die "setsid failed: $!"; exec @ARGV or die "exec failed: $!";'
    command = f'/usr/bin/perl -MPOSIX=setsid -e {shlex.quote(launcher)} -- {get_executable_path()}'

    log_fd, log_path = tempfile.mkstemp(prefix='rch-elevated-', suffix='.log')
    os.close(log_fd)
    log_file = shlex.quote(log_path)
    script = (
        f'cd {shlex.quote(get_runtime_root())} || exit 1; '
        f'{command} </dev/null >>{log_file} 2>&1 & '
        'rch_pid=$!; sleep 1; '
        'if kill -0 "$rch_pid" 2>/dev/null; then '
        'printf "RCH_ELEVATED_CLIENT_PID=%s\\n" "$rch_pid"; '
        f'printf "RCH_ELEVATED_CLIENT_LOG=%s\\n" {log_file}; '
        'else '
        f'tail -c 3000 {log_file} 2>/dev/null; '
        'exit 1; fi'
    )
    applescript = (
        f'do shell script "{escape_osascript_text(script)}" '
        'with administrator privileges'
    )
    try:
        result = subprocess.run(
            ['osascript', '-e', applescript], capture_output=True,
            text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 0, f'Elevated Client launch failed: {exc} (startup log: {log_path})'
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        return 0, f'Elevated Client launch failed: {detail or f"osascript exited {result.returncode}"} (startup log: {log_path})'
    match = re.search(r'RCH_ELEVATED_CLIENT_PID=(\d+)', result.stdout or '')
    if not match:
        return 0, f'Elevated Client launch failed: no Client PID (startup log: {log_path})'
    return 1, (
        f'Elevated Client process started (PID: {int(match.group(1))}) '
        f'(startup stderr: {log_path}); connection not yet verified'
    )


def _spawn_elevated_win():
    """Request UAC and report the detached Client PID from the launch status file."""
    from client.runtime.temp_workspace import get_temp_category_dir

    try:
        work_dir = tempfile.mkdtemp(
            prefix='client_elevation_',
            dir=get_temp_category_dir('client_logs', private=True),
        )
        status_path = os.path.join(work_dir, 'launch-status.json')
        log_path = os.path.join(work_dir, 'spawn.log')
        executable, parameters = _detached_launch_arguments(status_path, log_path)
        result = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', executable, parameters, os.getcwd(), 0,
        )
        if result <= 32:
            shutil.rmtree(work_dir, ignore_errors=True)
            return 0, f'Elevated Client launch failed (ShellExecuteW: {result})'

        status = _wait_for_detached_launch_status(status_path)
        if status.get('ok') and int(status.get('pid') or 0) > 0:
            return 1, f'Elevated detached Client started, PID: {status["pid"]}. Startup log: {log_path}'
        detail = str(status.get('error') or 'No child PID reported')
        return 0, f'Elevated detached Client launch failed: {detail}. Startup log: {log_path}'
    except Exception as exc:
        return 0, f'Elevated Client launch failed: {exc}'


def _detached_launch_arguments(status_path, log_path):
    """Use an elevated Python host to start the real Client detached."""
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


def _wait_for_detached_launch_status(status_path):
    deadline = time.monotonic() + _DETACHED_RESULT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if os.path.isfile(status_path):
            with open(status_path, 'r', encoding='utf-8') as stream:
                return json.load(stream)
        time.sleep(0.1)
    return {'ok': False, 'error': 'Elevated Python helper did not return a launch result'}
