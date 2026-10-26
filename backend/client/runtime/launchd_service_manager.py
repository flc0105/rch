import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

from client.runtime.client_util import get_executable_path, get_runtime_root
from client.runtime.launch_context import LAUNCH_MODE_ENV, LAUNCH_SOURCE_ENV
from client.runtime.user_identity import (
    get_posix_user_identity,
    resolve_macos_target_user_identity,
)


DEFAULT_LAUNCHD_LABEL = 'com.rch.client'
VALID_LAUNCHD_ACTIONS = {
    'install',
    'start',
    'stop',
    'restart',
    'uninstall',
    'status',
}
_VALID_LABEL_RE = re.compile(r'^[A-Za-z0-9._-]+$')


class LaunchdServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class LaunchdTarget:
    kind: str
    scope: str
    label: str
    plist_path: str
    domain: str
    service_target: str
    uid: int
    gid: int
    username: str
    home: str
    log_dir: str


def _normalize_label(label: str) -> str:
    normalized = str(label or DEFAULT_LAUNCHD_LABEL).strip()
    if not normalized or not _VALID_LABEL_RE.fullmatch(normalized):
        raise ValueError(f'Invalid launchd label: {label}')
    return normalized


def resolve_launchd_target(*, kind: str, label: str = DEFAULT_LAUNCHD_LABEL,
                           scope: str = 'user', target_user=None) -> LaunchdTarget:
    normalized_kind = str(kind or '').strip().lower()
    normalized_label = _normalize_label(label)

    if normalized_kind == 'daemon':
        root = get_posix_user_identity(0)
        plist_path = os.path.join('/Library/LaunchDaemons', f'{normalized_label}.plist')
        return LaunchdTarget(
            kind='daemon',
            scope='system',
            label=normalized_label,
            plist_path=plist_path,
            domain='system',
            service_target=f'system/{normalized_label}',
            uid=int(root.uid),
            gid=int(root.gid),
            username=root.username or 'root',
            home=root.home or '/var/root',
            log_dir='/Library/Logs/RCH',
        )

    if normalized_kind != 'agent':
        raise ValueError(f'Unsupported launchd service kind: {kind}')

    normalized_scope = str(scope or 'user').strip().lower()
    if normalized_scope not in {'user', 'global'}:
        raise ValueError(f'Unsupported LaunchAgent scope: {scope}')

    identity = resolve_macos_target_user_identity(target_user)
    if normalized_scope == 'user':
        plist_dir = os.path.join(identity.home, 'Library', 'LaunchAgents')
    else:
        plist_dir = '/Library/LaunchAgents'

    return LaunchdTarget(
        kind='agent',
        scope=normalized_scope,
        label=normalized_label,
        plist_path=os.path.join(plist_dir, f'{normalized_label}.plist'),
        domain=f'gui/{identity.uid}',
        service_target=f'gui/{identity.uid}/{normalized_label}',
        uid=int(identity.uid),
        gid=int(identity.gid),
        username=identity.username,
        home=identity.home,
        log_dir=os.path.join(identity.home, 'Library', 'Logs', 'RCH'),
    )


class LaunchdServiceManager:
    """Manage one LaunchAgent or LaunchDaemon using explicit launchd domains."""

    def __init__(self, *, kind: str, label: str = DEFAULT_LAUNCHD_LABEL,
                 scope: str = 'user', target_user=None, keep_alive: bool = True,
                 run_at_load: bool = True, command: str = '', working_directory: str = ''):
        if sys.platform != 'darwin':
            raise LaunchdServiceError('launchd service management is only available on macOS')

        self.target = resolve_launchd_target(
            kind=kind,
            label=label,
            scope=scope,
            target_user=target_user,
        )
        self.keep_alive = bool(keep_alive)
        self.run_at_load = bool(run_at_load)
        self.command = str(command or get_executable_path()).strip()
        self.working_directory = os.path.abspath(
            str(working_directory or get_runtime_root()).strip()
        )
        self._launchctl_path = shutil.which('launchctl') or '/bin/launchctl'

        if not self.command:
            raise ValueError('launchd command is required')
        try:
            self.program_arguments = shlex.split(self.command, posix=True)
        except ValueError as exc:
            raise ValueError(f'Invalid launchd command: {exc}') from exc
        if not self.program_arguments:
            raise ValueError('launchd command is empty')

    def execute(self, action: str) -> dict:
        normalized = str(action or 'status').strip().lower()
        if normalized not in VALID_LAUNCHD_ACTIONS:
            raise ValueError(f'Unsupported launchd action: {action}')

        if normalized == 'install':
            return self.install()
        if normalized == 'start':
            return self.start()
        if normalized == 'stop':
            return self.stop()
        if normalized == 'restart':
            return self.restart()
        if normalized == 'uninstall':
            return self.uninstall()
        return self.status()

    def status(self) -> dict:
        installed = os.path.isfile(self.target.plist_path)
        result = self._run_launchctl('print', self.target.service_target, check=False)
        loaded = result.returncode == 0
        stdout = str(result.stdout or '') if loaded else ''

        pid = None
        if loaded:
            match = re.search(r'^\s*pid\s*=\s*(\d+)\s*$', stdout, flags=re.MULTILINE)
            if match:
                pid = int(match.group(1))

        state = ''
        if loaded:
            match = re.search(r'^\s*state\s*=\s*([^\n]+?)\s*$', stdout, flags=re.MULTILINE)
            if match:
                state = str(match.group(1) or '').strip().lower()

        return {
            'ok': True,
            'action': 'status',
            'kind': self.target.kind,
            'scope': self.target.scope,
            'label': self.target.label,
            'target_user': self.target.username if self.target.kind == 'agent' else 'root',
            'target_uid': self.target.uid,
            'plist_path': self.target.plist_path,
            'domain': self.target.domain,
            'service_target': self.target.service_target,
            'installed': installed,
            'loaded': loaded,
            'running': bool(pid is not None or state == 'running'),
            'pid': pid,
            'state': state,
        }

    def install(self) -> dict:
        self._require_install_privilege()
        current = self.status()
        if current['loaded']:
            self._run_launchctl('bootout', self.target.service_target, check=True)

        self._prepare_install_directories()
        self._write_plist(self._build_plist())
        return self._result('install', 'Service definition installed; run start to activate it')

    def start(self) -> dict:
        self._require_control_privilege()
        current = self.status()
        if not current['installed']:
            raise LaunchdServiceError(f'Service is not installed: {self.target.plist_path}')

        if not current['loaded']:
            self._run_launchctl(
                'bootstrap', self.target.domain, self.target.plist_path, check=True,
            )

        kickstart = self._run_launchctl(
            'kickstart', '-p', self.target.service_target, check=True,
        )
        return self._result(
            'start',
            'Service started',
            command_pid=self._parse_pid_text(kickstart.stdout),
        )

    def stop(self) -> dict:
        self._require_control_privilege()
        current = self.status()
        if current['loaded']:
            # bootout is the durable current-session stop for KeepAlive services.
            # The plist remains installed and start() can bootstrap it again.
            self._run_launchctl('bootout', self.target.service_target, check=True)
        return self._result('stop', 'Service stopped; definition remains installed')

    def restart(self) -> dict:
        self._require_control_privilege()
        current = self.status()
        if not current['installed']:
            raise LaunchdServiceError(f'Service is not installed: {self.target.plist_path}')

        if not current['loaded']:
            started = self.start()
            started['action'] = 'restart'
            started['message'] = 'Service was stopped and has been started'
            return started

        kickstart = self._run_launchctl(
            'kickstart', '-kp', self.target.service_target, check=True,
        )
        return self._result(
            'restart',
            'Service restarted',
            command_pid=self._parse_pid_text(kickstart.stdout),
        )

    def uninstall(self) -> dict:
        self._require_install_privilege()
        current = self.status()
        if current['loaded']:
            self._run_launchctl('bootout', self.target.service_target, check=True)

        try:
            os.remove(self.target.plist_path)
        except FileNotFoundError:
            pass

        return self._result('uninstall', 'Service definition removed')

    def _result(self, action: str, message: str, command_pid=None) -> dict:
        status = self.status()
        status['action'] = action
        status['message'] = message
        if command_pid is not None and status.get('pid') is None:
            status['pid'] = int(command_pid)
            status['running'] = True
        return status

    def _build_plist(self) -> dict:
        launch_mode = 'user_service' if self.target.kind == 'agent' else 'system_service'
        launch_source = 'launchagent' if self.target.kind == 'agent' else 'launchdaemon'
        payload = {
            'Label': self.target.label,
            'ProgramArguments': list(self.program_arguments),
            'WorkingDirectory': self.working_directory,
            'RunAtLoad': self.run_at_load,
            'KeepAlive': self.keep_alive,
            'EnvironmentVariables': {
                LAUNCH_MODE_ENV: launch_mode,
                LAUNCH_SOURCE_ENV: launch_source,
            },
        }

        if self.target.kind == 'daemon':
            payload['UserName'] = 'root'
            payload['StandardOutPath'] = os.path.join(
                self.target.log_dir, f'{self.target.label}.out.log'
            )
            payload['StandardErrorPath'] = os.path.join(
                self.target.log_dir, f'{self.target.label}.err.log'
            )
        elif self.target.scope == 'user':
            payload['StandardOutPath'] = os.path.join(
                self.target.log_dir, f'{self.target.label}.out.log'
            )
            payload['StandardErrorPath'] = os.path.join(
                self.target.log_dir, f'{self.target.label}.err.log'
            )

        return payload

    def _prepare_install_directories(self):
        plist_dir = os.path.dirname(self.target.plist_path)
        if self.target.kind == 'daemon' or self.target.scope == 'global':
            os.makedirs(plist_dir, mode=0o755, exist_ok=True)
        else:
            os.makedirs(plist_dir, mode=0o755, exist_ok=True)
            if os.geteuid() == 0:
                os.chown(plist_dir, self.target.uid, self.target.gid)

        if self.target.kind == 'daemon':
            os.makedirs(self.target.log_dir, mode=0o755, exist_ok=True)
        elif self.target.scope == 'user':
            os.makedirs(self.target.log_dir, mode=0o700, exist_ok=True)
            if os.geteuid() == 0:
                os.chown(self.target.log_dir, self.target.uid, self.target.gid)
            os.chmod(self.target.log_dir, 0o700)

    def _write_plist(self, payload: dict):
        target = self.target.plist_path
        temp_path = f'{target}.tmp.{os.getpid()}'
        try:
            with open(temp_path, 'wb') as file_obj:
                plistlib.dump(payload, file_obj, sort_keys=True)
            os.chmod(temp_path, 0o644)
            if os.geteuid() == 0:
                if self.target.kind == 'agent' and self.target.scope == 'user':
                    os.chown(temp_path, self.target.uid, self.target.gid)
                else:
                    os.chown(temp_path, 0, 0)
            os.replace(temp_path, target)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    def _run_launchctl(self, *args, check: bool):
        result = subprocess.run(
            [self._launchctl_path, *args],
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            detail = str(result.stderr or result.stdout or '').strip()
            suffix = f': {detail}' if detail else ''
            raise LaunchdServiceError(
                f'launchctl {" ".join(args)} failed with exit code {result.returncode}{suffix}'
            )
        return result

    def _require_control_privilege(self):
        euid = int(os.geteuid())
        if self.target.kind == 'daemon' and euid != 0:
            raise PermissionError('LaunchDaemon start/stop/restart requires a root Client')
        if self.target.kind == 'agent' and euid not in {0, self.target.uid}:
            raise PermissionError(
                f'LaunchAgent control requires root or target uid {self.target.uid}'
            )

    def _require_install_privilege(self):
        euid = int(os.geteuid())
        if self.target.kind == 'daemon' or self.target.scope == 'global':
            if euid != 0:
                raise PermissionError(
                    f'{self.target.kind} {self.target.scope} install/uninstall requires a root Client'
                )
            return
        if euid not in {0, self.target.uid}:
            raise PermissionError(
                f'LaunchAgent install/uninstall requires root or target uid {self.target.uid}'
            )

    @staticmethod
    def _parse_pid_text(value):
        text = str(value or '').strip()
        return int(text) if text.isdigit() else None


def manage_launchd_service(*, kind: str, action: str, label: str = DEFAULT_LAUNCHD_LABEL,
                           scope: str = 'user', target_user=None, keep_alive: bool = True,
                           run_at_load: bool = True, command: str = '',
                           working_directory: str = '') -> dict:
    manager = LaunchdServiceManager(
        kind=kind,
        label=label,
        scope=scope,
        target_user=target_user,
        keep_alive=keep_alive,
        run_at_load=run_at_load,
        command=command,
        working_directory=working_directory,
    )
    return manager.execute(action)


def format_launchd_service_result(result: dict) -> str:
    row = dict(result or {})
    lines = [
        f"Action: {row.get('action', '-')}",
        f"Kind: {row.get('kind', '-')}",
        f"Label: {row.get('label', '-')}",
        f"Target: {row.get('target_user', '-')} ({row.get('domain', '-')})",
        f"Installed: {'yes' if row.get('installed') else 'no'}",
        f"Loaded: {'yes' if row.get('loaded') else 'no'}",
        f"Running: {'yes' if row.get('running') else 'no'}",
        f"PID: {row.get('pid') if row.get('pid') is not None else '-'}",
        f"Plist: {row.get('plist_path', '-')}",
    ]
    message = str(row.get('message') or '').strip()
    if message:
        lines.append(f'Message: {message}')
    return '\n'.join(lines)
