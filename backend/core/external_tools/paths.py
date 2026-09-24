import os
import re
import shlex
from typing import Any, Callable


_INSTANCE_PATTERN = re.compile(r'[^A-Za-z0-9_.-]+')

EXTERNAL_TOOLS_INSTALL_ROOT = '~/.ops/external_tools/installed'
EXTERNAL_TOOLS_RUNTIME_ROOT = '~/.ops/external_tools/runtime'
EXTERNAL_TOOLS_PACKAGE_CACHE_ROOT = '~/.ops/external_tools/packages'


def expand_path(path: Any) -> str:
    return os.path.abspath(os.path.expandvars(os.path.expanduser(str(path or '').strip())))


def sanitize_instance_id(value: Any) -> str:
    text = str(value or '').strip()
    text = _INSTANCE_PATTERN.sub('-', text).strip('.-_')
    return (text or 'default')[:96]


def external_tool_instances_runtime_parts(package_id: Any, module_id: Any) -> tuple[str, ...]:
    package = str(package_id or '').strip()
    module = str(module_id or '').strip()
    if module:
        return package, module, 'instances'
    return package, 'instances'


def external_tool_instance_runtime_parts(package_id: Any, module_id: Any, instance_id: Any) -> tuple[str, ...]:
    return (*external_tool_instances_runtime_parts(package_id, module_id), sanitize_instance_id(instance_id))


def external_tool_oneshot_runtime_parts(package_id: Any, module_id: Any, run_id: Any) -> tuple[str, ...]:
    package = str(package_id or '').strip()
    module = str(module_id or '').strip()
    run = sanitize_instance_id(run_id)
    return package, module, 'oneshot', run


def render_path_list(values: Any) -> list[str]:
    if isinstance(values, str):
        return shlex.split(values)
    if isinstance(values, list):
        return [str(item) for item in values]
    return []


def is_url_like(value: Any) -> bool:
    text = str(value or '').strip().lower()
    if '://' not in text:
        return False
    scheme = text.split('://', 1)[0]
    return bool(scheme) and all(ch.isalnum() or ch in '+-.' for ch in scheme)


def should_expand_argv_item(value: Any, index: int) -> bool:
    text = str(value or '').strip()
    if not text:
        return False
    if is_url_like(text):
        return False
    if index == 0:
        return True
    return (
        text.startswith('~')
        or text.startswith('/')
        or text.startswith('./')
        or text.startswith('../')
        or text.startswith('.\\')
        or text.startswith('..\\')
        or ('\\' in text)
    )


def chmod_executable(path: Any):
    text = str(path or '').strip()
    if not text or os.name == 'nt' or not os.path.exists(text):
        return
    mode = os.stat(text).st_mode
    os.chmod(text, mode | 0o111)


def path_has_content(path: Any) -> bool:
    text = str(path or '').strip()
    if not text or not os.path.exists(text):
        return False
    if os.path.isfile(text):
        return True
    if os.path.isdir(text):
        try:
            return any(os.scandir(text))
        except OSError:
            return False
    return True


def build_command_map(exec_paths: dict, path_expander: Callable[[Any], str] = expand_path) -> dict:
    commands = {}
    for name, path in (exec_paths or {}).items():
        text = str(path or '').strip()
        if not text:
            continue
        commands[str(name)] = shlex.quote(path_expander(text))
    return commands
