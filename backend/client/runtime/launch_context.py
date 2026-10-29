import os
import sys


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


LAUNCHD_SOURCES = {'launchagent', 'launchdaemon'}


def is_launchd_managed_client() -> bool:
    """Return whether launchd owns this Client's process lifecycle."""
    explicit_mode = str(os.environ.get(LAUNCH_MODE_ENV) or '').strip().lower()
    explicit_source = str(os.environ.get(LAUNCH_SOURCE_ENV) or '').strip().lower()
    if explicit_source in LAUNCHD_SOURCES and explicit_mode in {'user_service', 'system_service'}:
        return True

    if sys.platform != 'darwin':
        return False

    context = detect_launch_context('macos')
    return str(context.get('source') or '').strip().lower() in LAUNCHD_SOURCES


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
    if explicit_mode in VALID_LAUNCH_MODES:
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
        if direct_parent[0] == 'services.exe' or direct_parent[1].endswith(('\\services.exe', '/services.exe')):
            return {'mode': 'system_service', 'source': 'windows_service'}
    else:
        if has_any(('/cron', '/crond', ' cron', ' crond')) or any(
            row[0] in {'cron', 'crond'} for row in parent_rows
        ):
            return {'mode': 'scheduled', 'source': 'cron'}

        systemd_rows = [row for row in parent_rows if row[0] == 'systemd' or '/systemd' in row[1]]
        direct_systemd = bool(systemd_rows and direct_parent in systemd_rows)
        if os.environ.get('INVOCATION_ID') or direct_systemd:
            user_managed = any('--user' in row[2] for row in systemd_rows)
            return {
                'mode': 'user_service' if user_managed else 'system_service',
                'source': 'systemd_user' if user_managed else 'systemd',
            }

        if os_alias in {'mac', 'macos'} or sys.platform == 'darwin':
            xpc_service = str(os.environ.get('XPC_SERVICE_NAME') or '').strip()
            direct_launchd = direct_parent[0] == 'launchd' or direct_parent[1].endswith('/launchd')
            is_launchd_job = bool(
                direct_launchd
                or (
                    xpc_service
                    and xpc_service != '0'
                    and not xpc_service.startswith('application.')
                )
            )
            if is_launchd_job:
                try:
                    is_system = os.getuid() == 0
                except Exception:
                    is_system = False
                return {
                    'mode': 'system_service' if is_system else 'user_service',
                    'source': 'launchdaemon' if is_system else 'launchagent',
                }

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

    return {'mode': 'unknown', 'source': ''}
