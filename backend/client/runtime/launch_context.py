import os
import re
import subprocess
import sys
from functools import lru_cache


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


def _verified_systemd_unit_for_pid(pid: int):
    """Verify that this Linux process is the MainPID of an active .service unit.

    A parent named systemd or an inherited INVOCATION_ID cannot establish
    supervision: detached children can outlive their original parent.
    """
    if sys.platform != 'linux':
        return None
    try:
        with open(f'/proc/{pid}/cgroup', encoding='utf-8') as handle:
            memberships = [line.strip().split(':', 2) for line in handle]
    except (OSError, UnicodeError):
        return None
    for fields in memberships:
        if len(fields) != 3 or fields[1] not in ('', 'name=systemd'):
            continue
        segments = fields[2].strip('/').split('/')
        # systemd's login user@UID.service is itself a system service; a
        # process inside its app.slice is not automatically its MainPID.
        units = [part for part in segments if part.endswith('.service')
                 and not re.fullmatch(r'user@\d+\.service', part)]
        if not units:
            continue
        unit = units[-1]
        user_unit = any(
            re.fullmatch(r'user@\d+\.service', part) for part in segments
        )
        command = ['systemctl']
        if user_unit:
            command.append('--user')
        command.extend(['show', unit, '--property=MainPID', '--property=ActiveState'])
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=2, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        properties = dict(line.split('=', 1) for line in result.stdout.splitlines()
                          if '=' in line)
        if properties.get('MainPID') == str(pid) and properties.get('ActiveState') == 'active':
            return {'mode': 'user_service' if user_unit else 'system_service',
                    'source': 'systemd_user' if user_unit else 'systemd'}
    return None


def _verified_windows_service_for_pid(pid: int):
    """Match the current process PID to a running Service Control Manager entry."""
    try:
        import psutil
        iterator = psutil.win_service_iter()
        for service in iterator:
            data = service.as_dict()
            if data.get('status') == 'running' and int(data.get('pid') or 0) == pid:
                return {'mode': 'system_service', 'source': 'windows_service'}
    except (AttributeError, OSError, ValueError, TypeError, psutil.Error):
        pass
    return None


def detect_launch_context(os_alias: str) -> dict:
    """Classify the Client from operating-system process and supervisor facts."""
    # Product-level classification uses the canonical platform identity.
    # Native launchctl/systemd/Win32 API guards above still use the host OS.
    is_macos = os_alias == 'mac'
    if os_alias == 'ios':
        return {'mode': 'ide', 'source': 'pythonista'}

    is_windows = os_alias == 'win'
    is_linux = os_alias == 'linux'

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
        service = _verified_windows_service_for_pid(os.getpid())
        if service is not None:
            return service
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

    else:
        if has_any(('/cron', '/crond', ' cron', ' crond')) or any(
            row[0] in {'cron', 'crond'} for row in parent_rows
        ):
            return {'mode': 'scheduled', 'source': 'cron'}

        if is_linux:
            managed = _verified_systemd_unit_for_pid(os.getpid())
            if managed is not None:
                return managed

        if is_macos:
            managed = _verified_launchd_job_for_pid(os.getpid())
            if managed is not None:
                return managed

    def has_interactive_terminal():
        if is_windows:
            # Windows can retain console handles (or report isatty()) even when
            # a new process was created with DETACHED_PROCESS. Ask the OS if
            # *this process* belongs to a console before inspecting I/O.
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                get_console_process_list = kernel32.GetConsoleProcessList
                get_console_process_list.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
                get_console_process_list.restype = ctypes.c_uint32
                process_ids = (ctypes.c_uint32 * 1)()
                if get_console_process_list(process_ids, 1) == 0:
                    return False
            except (AttributeError, OSError, TypeError, ValueError):
                # Without a confirmed console attachment, prefer Detached.
                return False

        for stream in (sys.stdin, sys.stdout, sys.stderr):
            try:
                if stream is not None and stream.isatty():
                    return True
            except Exception:
                continue
        if is_windows:
            try:
                get_std_handle = kernel32.GetStdHandle
                get_std_handle.argtypes = [ctypes.c_uint32]
                get_std_handle.restype = ctypes.c_void_p
                get_console_mode = kernel32.GetConsoleMode
                get_console_mode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
                get_console_mode.restype = ctypes.c_int
                mode = ctypes.c_uint32()
                for stream_id in (-10, -11, -12):
                    handle = get_std_handle(stream_id)
                    if handle and handle != ctypes.c_void_p(-1).value:
                        if get_console_mode(handle, ctypes.byref(mode)):
                            return True
            except (AttributeError, OSError, TypeError, ValueError):
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
        # A short-lived PowerShell/cmd bootstrap may still be the parent at
        # startup. Without an attached console the child is a detached process.
        if is_windows and not interactive_terminal:
            return {'mode': 'detached', 'source': 'detached_process'}
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
