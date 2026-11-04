import os
import re
import subprocess
import sys
from functools import lru_cache


LAUNCH_MODE_ENV = 'RCH_CLIENT_LAUNCH_MODE'
LAUNCH_SOURCE_ENV = 'RCH_CLIENT_LAUNCH_SOURCE'
VALID_LAUNCH_MODES = {
    'terminal',
    'terminal_background',
    'ide',
    'detached',
    'user_service',
    'system_service',
    'scheduled',
    'unknown',
}



@lru_cache(maxsize=4)
def _verified_launchd_job_for_pid(pid: int):
    """Identify a running launchd *job*, not a process merely adopted by launchd.

    `launchctl list` supplies a running job's label and PID in the current
    bootstrap domain. Verify the exact job with `launchctl print` in an
    explicit domain; an anonymous job or a PID in another job is not proof.
    """
    if sys.platform != 'darwin':
        return None

    try:
        listed = subprocess.run(
            ['/bin/launchctl', 'list'], capture_output=True, text=True,
            timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listed.returncode != 0:
        return None

    labels = []
    for line in listed.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3 or fields[0] != str(pid):
            continue
        label = fields[2].strip()
        # launchd also tracks adopted/anonymous processes. Only named jobs count.
        if not label or 'anonymous' in label.lower() or '/' in label:
            continue
        labels.append(label)

    if not labels:
        return None

    try:
        uid = os.getuid()
    except (AttributeError, OSError):
        return None

    for label in labels:
        for domain, expected_type, mode, source in (
            (f'gui/{uid}', 'LaunchAgent', 'user_service', 'launchagent'),
            (f'user/{uid}', 'LaunchAgent', 'user_service', 'launchagent'),
            ('system', 'LaunchDaemon', 'system_service', 'launchdaemon'),
        ):
            try:
                detail = subprocess.run(
                    ['/bin/launchctl', 'print', f'{domain}/{label}'],
                    capture_output=True, text=True, timeout=2, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if detail.returncode != 0:
                continue
            output = detail.stdout
            if (re.search(r'^[ \t]*pid[ \t]*=[ \t]*' + re.escape(str(pid)) + r'[ \t]*$', output, re.M)
                    and re.search(r'^[ \t]*state[ \t]*=[ \t]*running[ \t]*$', output, re.M | re.I)
                    and re.search(r'^[ \t]*type[ \t]*=[ \t]*' + expected_type + r'[ \t]*$', output, re.M | re.I)):
                return {'mode': mode, 'source': source}
    return None


def is_launchd_managed_client() -> bool:
    """Only an actual matching launchd job can own the macOS Client."""
    if sys.platform != 'darwin':
        return False
    return _verified_launchd_job_for_pid(os.getpid()) is not None


def with_launch_context_environment(source=None, *, mode: str, launch_source: str = '') -> dict:
    """Return an environment carrying only the normalized launch shape of a new Client."""
    env = dict(os.environ if source is None else source)
    normalized_mode = str(mode or '').strip().lower()
    if normalized_mode not in VALID_LAUNCH_MODES:
        raise ValueError(f'Unsupported launch mode: {mode}')

    env[LAUNCH_MODE_ENV] = normalized_mode
    normalized_source = str(launch_source or '').strip().lower()
    if normalized_source:
        env[LAUNCH_SOURCE_ENV] = normalized_source
    else:
        env.pop(LAUNCH_SOURCE_ENV, None)
    return env


def detached_launch_environment(source=None) -> dict:
    launch_source = 'detached_process' if os.name == 'nt' else 'new_session'
    return with_launch_context_environment(
        source,
        mode='detached',
        launch_source=launch_source,
    )


def detect_launch_context(os_alias: str) -> dict:
    """Classify the current Client by its external process-hosting mode."""
    explicit_mode = str(os.environ.get(LAUNCH_MODE_ENV) or '').strip().lower()
    is_macos = os_alias in {'mac', 'macos'} or sys.platform == 'darwin'
    # On macOS the OS process/job state is authoritative. Inherited launch
    # markers can describe a former parent, not the current process.
    if not is_macos and explicit_mode in VALID_LAUNCH_MODES:
        return {
            'mode': explicit_mode,
            'source': str(os.environ.get(LAUNCH_SOURCE_ENV) or '').strip().lower(),
        }

    if os_alias == 'ios':
        return {'mode': 'ide', 'source': 'pythonista'}

    is_windows = os_alias in {'win', 'windows'} or os.name == 'nt'

    try:
        import psutil

        parents = psutil.Process().parents()
    except Exception:
        parents = []

    def process_text(item):
        try:
            name = str(item.name() or '').strip().lower()
        except Exception:
            name = ''
        try:
            executable = str(item.exe() or '').strip().lower()
        except Exception:
            executable = ''
        try:
            command = ' '.join(str(part) for part in (item.cmdline() or [])).strip().lower()
        except Exception:
            command = ''
        return name, executable, command

    parent_rows = [process_text(item) for item in parents]
    direct_parent = parent_rows[0] if parent_rows else ('', '', '')

    def has_any(tokens):
        return any(
            token in value
            for row in parent_rows
            for value in row
            for token in tokens
        )

    if is_windows:
        if has_any(('taskeng.exe', 'taskhostw.exe', 'schtasks.exe')):
            return {'mode': 'scheduled', 'source': 'schtasks'}

        # Modern Task Scheduler launches tasks from the Schedule service's
        # svchost.exe, rather than necessarily via taskeng.exe/taskhostw.exe.
        schedule_pid = None
        try:
            service = psutil.win_service_get('Schedule')
            schedule_pid = int(service.as_dict().get('pid') or 0)
        except (AttributeError, ValueError, TypeError, OSError, psutil.Error):
            pass
        for item, row in zip(parents, parent_rows):
            if row[0] != 'svchost.exe':
                continue
            if schedule_pid:
                try:
                    if int(item.pid) == schedule_pid:
                        return {'mode': 'scheduled', 'source': 'schtasks'}
                except (AttributeError, ValueError, TypeError):
                    pass
            # The dedicated svchost host also advertises the Schedule service.
            if re.search(r'(?<!\S)-s\s+schedule(?=\s|$)', row[2]):
                return {'mode': 'scheduled', 'source': 'schtasks'}

        if direct_parent[0] == 'services.exe' or direct_parent[1].endswith(('\\services.exe', '/services.exe')):
            return {'mode': 'system_service', 'source': 'windows_service'}
    else:
        if has_any(('/cron', '/crond', ' cron', ' crond')) or any(
            row[0] in {'cron', 'crond'} for row in parent_rows
        ):
            return {'mode': 'scheduled', 'source': 'cron'}

        systemd_rows = [row for row in parent_rows if row[0] == 'systemd' or '/systemd' in row[1]]
        direct_systemd = bool(systemd_rows and direct_parent in systemd_rows)
        if not is_macos and (os.environ.get('INVOCATION_ID') or direct_systemd):
            user_managed = any('--user' in row[2] for row in systemd_rows)
            return {
                'mode': 'user_service' if user_managed else 'system_service',
                'source': 'systemd_user' if user_managed else 'systemd',
            }

        if is_macos:
            managed = _verified_launchd_job_for_pid(os.getpid())
            if managed is not None:
                return managed

    def has_interactive_terminal():
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            try:
                if stream is not None and stream.isatty():
                    return True
            except Exception:
                continue
        if is_windows:
            try:
                import ctypes
                return bool(ctypes.windll.kernel32.GetConsoleWindow())
            except Exception:
                pass
        return False

    interactive_terminal = has_interactive_terminal()

    if not is_windows and os.name == 'posix' and not interactive_terminal:
        try:
            if os.getsid(0) == os.getpid():
                return {'mode': 'detached', 'source': 'new_session'}
        except Exception:
            pass

    shell_sources = {
        'zsh': 'zsh', 'bash': 'bash', 'sh': 'sh', 'dash': 'dash',
        'fish': 'fish', 'ksh': 'ksh', 'tcsh': 'tcsh',
        'cmd.exe': 'cmd', 'powershell.exe': 'powershell', 'pwsh.exe': 'pwsh',
    }
    direct_name = direct_parent[0]
    shell_source = shell_sources.get(direct_name)
    if not shell_source:
        for shell_name, source in shell_sources.items():
            if direct_parent[1].endswith('/' + shell_name) or direct_parent[1].endswith('\\' + shell_name):
                shell_source = source
                break

    def is_background_terminal_job():
        if is_windows:
            return not interactive_terminal
        try:
            process_group = os.getpgrp()
        except Exception:
            return not interactive_terminal
        for fd in (0, 1, 2):
            try:
                if os.isatty(fd) and os.tcgetpgrp(fd) != process_group:
                    return True
            except Exception:
                continue
        return not interactive_terminal

    if shell_source:
        return {
            'mode': 'terminal_background' if is_background_terminal_job() else 'terminal',
            'source': shell_source,
        }

    if has_any(('pycharm', 'pydevd', 'jetbrains')) or os.environ.get('PYCHARM_HOSTED'):
        return {'mode': 'ide', 'source': 'pycharm'}

    if interactive_terminal:
        return {'mode': 'terminal', 'source': ''}

    if is_windows:
        return {'mode': 'detached', 'source': 'detached_process'}

    if is_macos and not interactive_terminal:
        # If the process is no longer associated with a controlling terminal,
        # it is running detached even when it is not the session leader.
        try:
            import psutil
            controlling_tty = psutil.Process().terminal()
        except (AttributeError, OSError, psutil.Error):
            pass
        else:
            if controlling_tty is None:
                return {'mode': 'detached', 'source': ''}

    return {'mode': 'unknown', 'source': ''}
