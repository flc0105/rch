import getpass
import os
import platform
import re
import shutil
import sys

from client.config.config import CLIENT_BUILD_VERSION
from client.runtime.client_util import (
    get_executable_path,
    get_runtime_root,
    get_system_paths,
    wrap_path,
)
from core.device.local_identity import get_local_identity
from core.utils.formatting import get_readable_time, get_time


class CommandVariableResolutionError(ValueError):
    pass


class CommandVariableResolver:
    """
    普通 command 的 Client 侧动态变量解析器。

    当前只支持三类命名空间：
    - ${rch:*}：RCH Client 运行时信息
    - ${env:*}：目标 Client 当前进程环境变量
    - ${path:*}：目标 Client 常用系统路径

    script / acmd 不经过本解析器。
    """

    VARIABLE_PATTERN = re.compile(
        r'\$\{(?P<namespace>rch|env|path)\\?:(?P<name>[^{}]+)\}',
        re.IGNORECASE,
    )
    NAMESPACED_VARIABLE_PATTERN = re.compile(
        r'\$\{(?P<namespace>[^:{}\\]+)\\?:(?P<name>[^{}]+)\}',
        re.IGNORECASE,
    )

    def __init__(self, connection):
        self.connection = connection
        self._static_cache = {}
        self._rch_variables = {
            'exec_path': ('Current Client process executable path.', self._get_exec_path),
            'launch_command': ('Current Client launch command.', self._get_launch_command),
            'runtime': ('RCH Client runtime root directory.', self._get_runtime),
            'pid': ('Current Client process ID.', self._get_pid),
            'uid': ('Current Client user name, equivalent to getuid.', self._get_uid),
            'cwd': ('Current Client working directory.', self._get_cwd),
            'shell': ('Preferred shell path on the target Client.', self._get_shell),
            'hostname': ('Target Client hostname.', self._get_hostname),
            'command_id': ('Current command ID.', self._get_command_id),
            'client_id': ('Current Client connection ID.', self._get_client_id),
            'machine_id': ('Current machine identity hash.', self._get_machine_id),
            'build_ver': ('Current Client build version.', self._get_build_version),
            'py_ver': ('Current Client Python version.', self._get_python_version),
            'platform': ('Current platform alias: win, mac, linux, or ios.', self._get_platform_alias),
            'os_type': ('Current platform display name.', self._get_os_type),
            'os_alias': ('Current platform alias.', self._get_platform_alias),
            'os_name': ('Current operating system name.', self._get_os_name),
            'os_ver': ('Current operating system version.', self._get_os_version),
            'arch': ('Current machine architecture.', self._get_arch),
            'manufacturer': ('Current machine manufacturer.', self._get_manufacturer),
            'model': ('Current machine model.', self._get_model),
            'timestamp': ('Current compact local timestamp: yyyyMMdd-HHmmss.', self._get_timestamp),
            'datetime': ('Current local date/time: yyyy-MM-dd HH:mm:ss.', self._get_datetime),
        }
        self._path_variables = {
            'home': 'Current user home directory.',
            'desktop': 'Current user Desktop directory.',
            'downloads': 'Current user Downloads directory.',
            'temp': 'Current temporary directory.',
        }

    def resolve(self, command, command_id=None) -> str:
        text = str(command or '')
        if '${' not in text:
            return text

        for match in self.NAMESPACED_VARIABLE_PATTERN.finditer(text):
            namespace = str(match.group('namespace') or '').strip().lower()
            if namespace not in {'rch', 'env', 'path'}:
                raise CommandVariableResolutionError(f'Unsupported variable namespace: {namespace}')

        def _replace(match):
            namespace = str(match.group('namespace') or '').strip().lower()
            name = str(match.group('name') or '').strip()
            if not name:
                raise CommandVariableResolutionError('Variable name is required')

            if namespace == 'rch':
                return self._resolve_rch(name, command_id=command_id)
            if namespace == 'env':
                return self._resolve_env(name)
            if namespace == 'path':
                return self._resolve_path(name)

            raise CommandVariableResolutionError(f'Unsupported variable namespace: {namespace}')

        return self.VARIABLE_PATTERN.sub(_replace, text)

    def get_manifest_payload(self) -> list[dict]:
        payload = []

        for name, (description, _provider) in self._rch_variables.items():
            payload.append(self._build_manifest_item('rch', name, description))

        for name, description in self._path_variables.items():
            payload.append(self._build_manifest_item('path', name, description))

        payload.append({
            'namespace': 'env',
            'name': 'NAME',
            'template': '${env:NAME}',
            'description': 'Read NAME from the target Client process environment at execution time.',
            'dynamic': True,
            'candidates': sorted(
                [str(name).strip() for name in os.environ.keys() if str(name).strip()],
                key=str.lower,
            ),
        })

        return payload

    def _build_manifest_item(self, namespace: str, name: str, description: str) -> dict:
        return {
            'namespace': namespace,
            'name': name,
            'template': '${' + namespace + ':' + name + '}',
            'description': description,
            'dynamic': True,
        }

    def _resolve_rch(self, name: str, command_id=None) -> str:
        key = str(name or '').strip().lower()
        item = self._rch_variables.get(key)
        if item is None:
            raise CommandVariableResolutionError(f'Unknown rch variable: {name}')

        _description, provider = item
        value = provider(command_id)
        return self._stringify_value(value, f'rch:{key}')

    def _resolve_env(self, name: str) -> str:
        key = str(name or '').strip()
        if not key:
            raise CommandVariableResolutionError('Environment variable name is required')

        value = os.environ.get(key)
        if value is None:
            raise CommandVariableResolutionError(f'Environment variable is not set: {key}')
        return str(value)

    def _resolve_path(self, name: str) -> str:
        key = str(name or '').strip().lower()
        if key not in self._path_variables:
            raise CommandVariableResolutionError(f'Unknown path variable: {name}')

        value = get_system_paths().get(key)
        return self._stringify_value(value, f'path:{key}')

    def _stringify_value(self, value, label: str) -> str:
        if value is None:
            raise CommandVariableResolutionError(f'Variable has no value: {label}')
        return str(value)

    def _get_static(self, key: str, factory):
        if key not in self._static_cache:
            self._static_cache[key] = factory()
        return self._static_cache[key]

    def _get_local_identity(self):
        return self._get_static('local_identity', get_local_identity)

    def _get_exec_path(self, _command_id=None):
        return wrap_path(os.path.realpath(sys.executable))

    def _get_launch_command(self, _command_id=None):
        return get_executable_path()

    def _get_runtime(self, _command_id=None):
        return get_runtime_root()

    def _get_pid(self, _command_id=None):
        return os.getpid()

    def _get_uid(self, _command_id=None):
        return getpass.getuser()

    def _get_cwd(self, _command_id=None):
        return os.getcwd()

    def _get_shell(self, _command_id=None):
        if os.name == 'nt':
            candidate = str(os.environ.get('COMSPEC') or '').strip() or shutil.which('cmd.exe')
            return os.path.realpath(candidate) if candidate else 'cmd.exe'

        candidates = [str(os.environ.get('SHELL') or '').strip()]
        try:
            import pwd
            candidates.append(str(pwd.getpwuid(os.getuid()).pw_shell or '').strip())
        except Exception:
            pass
        candidates.extend([
            shutil.which('zsh') or '',
            shutil.which('bash') or '',
            shutil.which('sh') or '',
        ])

        for candidate in candidates:
            if not candidate:
                continue
            resolved = candidate if os.path.isabs(candidate) else shutil.which(candidate)
            if resolved and os.path.isfile(resolved) and os.access(resolved, os.X_OK):
                return os.path.realpath(resolved)

        raise CommandVariableResolutionError('No supported shell found')

    def _get_hostname(self, _command_id=None):
        return self._get_local_identity().hostname

    def _get_command_id(self, command_id=None):
        return '' if command_id is None else command_id

    def _get_client_id(self, _command_id=None):
        return getattr(self.connection, 'client_id', '') or ''

    def _get_machine_id(self, _command_id=None):
        return self._get_local_identity().machine_id

    def _get_build_version(self, _command_id=None):
        return CLIENT_BUILD_VERSION

    def _get_python_version(self, _command_id=None):
        return platform.python_version()

    def _get_platform_alias(self, _command_id=None):
        return self._get_local_identity().os_alias

    def _get_os_type(self, _command_id=None):
        return self._get_local_identity().os_type

    def _get_os_name(self, _command_id=None):
        return self._get_local_identity().os_name

    def _get_os_version(self, _command_id=None):
        return self._get_local_identity().os_version

    def _get_arch(self, _command_id=None):
        return self._get_local_identity().arch

    def _get_manufacturer(self, _command_id=None):
        return self._get_local_identity().manufacturer

    def _get_model(self, _command_id=None):
        return self._get_local_identity().model

    def _get_timestamp(self, _command_id=None):
        return get_time()

    def _get_datetime(self, _command_id=None):
        return get_readable_time()
