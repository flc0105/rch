import os
import shlex
import shutil
import subprocess
import sys


def _normalize_prefix_args(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return shlex.split(value)
    return []


def _python_version(command_argv: list[str]) -> str:
    try:
        completed = subprocess.run(
            [*command_argv, '-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return ''
    if completed.returncode != 0:
        return ''
    return (completed.stdout or '').strip()


def _resolve_client_python_command() -> list[str]:
    if not getattr(sys, 'frozen', False):
        return [os.path.realpath(sys.executable)]

    candidates = []
    env_python = os.environ.get('PYTHON_EXECUTABLE', '').strip()
    if env_python:
        candidates.append([env_python])

    for name in ('python3', 'python'):
        path = shutil.which(name)
        if path:
            candidates.append([path])

    py_launcher = shutil.which('py')
    if py_launcher:
        candidates.append([py_launcher, '-3'])

    expected_version = f'{sys.version_info.major}.{sys.version_info.minor}'
    seen = set()
    for command_argv in candidates:
        key = tuple(command_argv)
        if key in seen:
            continue
        seen.add(key)
        if _python_version(command_argv) == expected_version:
            return command_argv

    raise RuntimeError(
        f'Python {expected_version} matching the current client runtime was not found'
    )


def _resolve_system_command(command: str) -> str:
    command = str(command or '').strip()
    if not command:
        raise ValueError('launcher.command is required for system launcher')

    expanded = os.path.expandvars(os.path.expanduser(command))
    if os.path.isabs(expanded) or os.path.dirname(expanded):
        if not os.path.isfile(expanded):
            raise FileNotFoundError(f'External tool launcher command not found: {command}')
        return os.path.realpath(expanded)

    resolved = shutil.which(expanded)
    if not resolved:
        raise FileNotFoundError(f'External tool launcher command not found in PATH: {command}')
    return os.path.realpath(resolved)


def resolve_external_tool_launcher(launcher, launcher_override=None) -> dict:
    if not isinstance(launcher, dict) or not launcher:
        return {
            'type': 'direct',
            'executable': '',
            'command_argv': [],
            'prefix_args': [],
        }

    launcher_type = str(launcher.get('type') or 'direct').strip().lower()
    prefix_args = _normalize_prefix_args(launcher.get('prefix_args'))
    if launcher_type in ('', 'direct'):
        return {
            'type': 'direct',
            'executable': '',
            'command_argv': [],
            'prefix_args': prefix_args,
        }

    override = launcher_override if isinstance(launcher_override, dict) else {}
    override_executable = str(override.get('executable') or '').strip()
    if override_executable:
        command_argv = [_resolve_system_command(override_executable)]
    elif launcher_type == 'client_python':
        command_argv = _resolve_client_python_command()
    elif launcher_type == 'system':
        command_argv = [_resolve_system_command(launcher.get('command') or '')]
    else:
        raise ValueError(f'Unsupported external tool launcher type: {launcher_type}')

    return {
        'type': launcher_type,
        'executable': command_argv[0],
        'command_argv': command_argv,
        'prefix_args': prefix_args,
    }


def apply_external_tool_launcher(argv: list[str], launcher, launcher_override=None) -> list[str]:
    source_argv = [str(item) for item in (argv or [])]
    if not source_argv:
        raise ValueError('runtime argv is required')

    resolved = resolve_external_tool_launcher(launcher, launcher_override=launcher_override)
    command_argv = resolved.get('command_argv') or []
    if not command_argv:
        return source_argv

    prefix_args = resolved.get('prefix_args') or []
    return [*command_argv, *prefix_args, source_argv[0], *source_argv[1:]]
