"""Request authorization to launch a separate elevated Client."""
import os
import re
import shlex
import subprocess
import tempfile

from client.commands.platform.utils.mac_util import escape_osascript_text
from client.commands.runtime.interrupts import timeout
from client.commands.shell.decorators import shell_command
from client.commands.shell.standalone._elevated_process import (
    ELEVATED_COMMAND_TIMEOUT,
    ElevationCancelled,
    run_authorized_process,
)
from client.runtime.client_util import get_executable_argv, get_executable_path, get_runtime_root
from client.runtime.execution.context import CommandTimeoutError
from core.utils.decorator import confirm


@shell_command('Launch a new instance with elevated privileges ([--no-confirm] skips RCH confirmation)',
               group='privilege', platforms=('mac', 'win'))
@timeout(ELEVATED_COMMAND_TIMEOUT)
@confirm('This may show an operating system permission prompt and wait for authorization. Continue?',
         platform_messages={'win': 'This may show a Windows UAC permission prompt and wait for authorization. Continue?'},
         no_arguments=True)
def spawn_elevated_instance(self, options=''):
    if self.command_platform == 'win':
        return _spawn_elevated_win(self)
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


def _spawn_elevated_win(owner):
    """Launch the real detached Client and preserve its startup diagnostics."""
    from client.runtime.temp_workspace import get_temp_category_dir
    from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV
    from client.watchdog.watchdog_environment import PROCESS_RECOVERY_WATCHDOG_ENV_KEYS

    log_path = None
    try:
        log_fd, log_path = tempfile.mkstemp(
            prefix='client-elevation-', suffix='.log',
            dir=get_temp_category_dir('client_logs', private=True),
        )
        os.close(log_fd)
        status, message = run_authorized_process(
            owner, 'win', 'detached', get_executable_argv(), startup_log=log_path,
            clear_env=[*PROCESS_RECOVERY_WATCHDOG_ENV_KEYS, RECOVERY_SOURCE_ENV],
        )
        return status, f'{message}. Startup log: {log_path}; connection not yet verified'
    except ElevationCancelled as exc:
        if log_path and os.path.isfile(log_path):
            os.unlink(log_path)
        return 0, str(exc)
    except (CommandTimeoutError, subprocess.TimeoutExpired) as exc:
        return 0, str(exc)
    except OSError as exc:
        log_hint = f' (startup log: {log_path})' if log_path else ''
        return 0, f'Elevated Client launch failed: {exc}{log_hint}'
