from dataclasses import dataclass
from types import SimpleNamespace

import psutil

import client.runtime.client_info_builder as client_info_builder
import client.runtime.client_util as client_util
import client.runtime.launch_context as launch_context
from client.runtime.client_info_builder import ClientInfoBuilder
from server.application.connection.connection_service import WebConnectionService
from server.application.connection.recent_device_store import RecentDeviceStore
from server.persistence.rch_database import RchDatabase


@dataclass
class _FakeParent:
    process_name: str
    executable: str = ''
    command: tuple[str, ...] = ()

    def name(self):
        return self.process_name

    def exe(self):
        return self.executable

    def cmdline(self):
        return list(self.command)


class _FakeProcess:
    def __init__(self, parents):
        self._parents = list(parents)

    def parents(self):
        return list(self._parents)


class _FakeStream:
    def __init__(self, is_tty):
        self._is_tty = bool(is_tty)

    def isatty(self):
        return self._is_tty


def _prepare(monkeypatch, parents=(), *, is_tty=False, platform='linux'):
    monkeypatch.setattr(psutil, 'Process', lambda: _FakeProcess(parents))
    monkeypatch.setattr(launch_context.sys, 'platform', platform)
    monkeypatch.setattr(launch_context.sys, 'stdin', _FakeStream(is_tty))
    monkeypatch.setattr(launch_context.sys, 'stdout', _FakeStream(is_tty))
    monkeypatch.setattr(launch_context.sys, 'stderr', _FakeStream(is_tty))
    monkeypatch.delenv('INVOCATION_ID', raising=False)
    monkeypatch.delenv('XPC_SERVICE_NAME', raising=False)
    monkeypatch.delenv('PYCHARM_HOSTED', raising=False)
    monkeypatch.delenv(launch_context.LAUNCH_MODE_ENV, raising=False)
    monkeypatch.delenv(launch_context.LAUNCH_SOURCE_ENV, raising=False)


def test_terminal_and_terminal_background_are_distinguished_by_tty(monkeypatch):
    zsh = _FakeParent('zsh', '/bin/zsh', ('-zsh',))
    _prepare(monkeypatch, [zsh], is_tty=True)
    assert ClientInfoBuilder._detect_launch_context('mac') == {'mode': 'terminal', 'source': 'zsh'}

    _prepare(monkeypatch, [zsh], is_tty=False)
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'terminal_background', 'source': 'zsh'
    }


def test_posix_background_job_is_detected_even_when_stdio_is_a_tty(monkeypatch):
    zsh = _FakeParent('zsh', '/bin/zsh', ('-zsh',))
    _prepare(monkeypatch, [zsh], is_tty=True)
    monkeypatch.setattr(launch_context.os, 'getpgrp', lambda: 200)
    monkeypatch.setattr(launch_context.os, 'isatty', lambda fd: fd == 0)
    monkeypatch.setattr(launch_context.os, 'tcgetpgrp', lambda _fd: 100)
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'terminal_background', 'source': 'zsh'
    }


def test_pycharm_run_is_ide_but_pycharm_terminal_remains_terminal(monkeypatch):
    python_parent = _FakeParent('python3', '/usr/bin/python3', ('python3', 'pydevd.py'))
    pycharm = _FakeParent('pycharm', '/Applications/PyCharm.app/Contents/MacOS/pycharm', ('pycharm',))
    _prepare(monkeypatch, [python_parent, pycharm], is_tty=False)
    assert ClientInfoBuilder._detect_launch_context('mac') == {'mode': 'ide', 'source': 'pycharm'}

    zsh = _FakeParent('zsh', '/bin/zsh', ('-zsh',))
    _prepare(monkeypatch, [zsh, pycharm], is_tty=True)
    assert ClientInfoBuilder._detect_launch_context('mac') == {'mode': 'terminal', 'source': 'zsh'}


def test_explicit_detached_shape_outranks_inherited_pycharm_context(monkeypatch):
    pycharm = _FakeParent('pycharm', '/Applications/PyCharm.app/Contents/MacOS/pycharm', ('pycharm',))
    _prepare(monkeypatch, [pycharm], is_tty=False)
    monkeypatch.setenv(launch_context.LAUNCH_MODE_ENV, 'detached')
    monkeypatch.setenv(launch_context.LAUNCH_SOURCE_ENV, 'new_session')
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'detached', 'source': 'new_session'
    }


def test_detached_launch_environment_records_shape_not_internal_action(monkeypatch):
    monkeypatch.setattr(launch_context.os, 'name', 'posix')
    env = launch_context.detached_launch_environment({'PYCHARM_HOSTED': '1'})
    assert env[launch_context.LAUNCH_MODE_ENV] == 'detached'
    assert env[launch_context.LAUNCH_SOURCE_ENV] == 'new_session'
    assert 'spawn_instance' not in env.values()
    assert 'relaunch_instance' not in env.values()


def test_spawn_new_instance_marks_the_new_client_as_detached(monkeypatch):
    captured = {}
    monkeypatch.setattr(client_util.os, 'name', 'posix')
    monkeypatch.setattr(client_util, 'get_executable_path', lambda: 'python3 /tmp/rchclient.py')
    monkeypatch.setattr(client_util.sys, 'argv', ['/tmp/rchclient.py'])
    monkeypatch.setattr(client_util.subprocess, 'Popen', lambda *args, **kwargs: captured.update({
        'args': args, 'kwargs': kwargs,
    }) or SimpleNamespace(pid=1234))

    client_util.spawn_new_instance()

    env = captured['kwargs']['env']
    assert env[launch_context.LAUNCH_MODE_ENV] == 'detached'
    assert env[launch_context.LAUNCH_SOURCE_ENV] == 'new_session'
    assert captured['kwargs']['start_new_session'] is True


def test_terminal_is_not_misclassified_by_systemd_or_launchd_ancestors(monkeypatch):
    bash = _FakeParent('bash', '/bin/bash', ('bash',))
    systemd = _FakeParent('systemd', '/usr/lib/systemd/systemd', ('systemd', '--user'))
    _prepare(monkeypatch, [bash, systemd], is_tty=True)
    assert ClientInfoBuilder._detect_launch_context('linux') == {
        'mode': 'terminal', 'source': 'bash'
    }

    zsh = _FakeParent('zsh', '/bin/zsh', ('zsh',))
    launchd = _FakeParent('launchd', '/sbin/launchd', ('/sbin/launchd',))
    _prepare(monkeypatch, [zsh, launchd], is_tty=True, platform='darwin')
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'terminal', 'source': 'zsh'
    }


def test_posix_new_session_without_tty_is_detached(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False)
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 1234)
    monkeypatch.setattr(launch_context.os, 'getsid', lambda _pid: 1234)
    assert ClientInfoBuilder._detect_launch_context('linux') == {
        'mode': 'detached', 'source': 'new_session'
    }


def test_macos_launchagent_and_launchdaemon(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False, platform='darwin')
    monkeypatch.setenv('XPC_SERVICE_NAME', 'com.example.rch.agent')
    monkeypatch.setattr(launch_context.os, 'getuid', lambda: 501)
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'user_service', 'source': 'launchagent'
    }

    monkeypatch.setattr(launch_context.os, 'getuid', lambda: 0)
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'system_service', 'source': 'launchdaemon'
    }

    launchd = _FakeParent('launchd', '/sbin/launchd', ('/sbin/launchd',))
    _prepare(monkeypatch, [launchd], is_tty=False, platform='darwin')
    monkeypatch.setattr(launch_context.os, 'getuid', lambda: 501)
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'user_service', 'source': 'launchagent'
    }


def test_cron_and_schtasks_outrank_intermediate_shell(monkeypatch):
    sh = _FakeParent('sh', '/bin/sh', ('sh', '-c', 'python3 rchclient.py'))
    cron = _FakeParent('cron', '/usr/sbin/cron', ('cron',))
    _prepare(monkeypatch, [sh, cron], is_tty=False)
    assert ClientInfoBuilder._detect_launch_context('mac') == {'mode': 'scheduled', 'source': 'cron'}

    cmd = _FakeParent('cmd.exe', r'C:\\Windows\\System32\\cmd.exe', ('cmd.exe', '/c', 'python rchclient.py'))
    task = _FakeParent('taskeng.exe', r'C:\\Windows\\System32\\taskeng.exe', ('taskeng.exe',))
    _prepare(monkeypatch, [cmd, task], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'scheduled', 'source': 'schtasks'
    }


def test_windows_terminal_and_detached_modes(monkeypatch):
    powershell = _FakeParent(
        'powershell.exe',
        r'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
        ('powershell.exe',),
    )
    _prepare(monkeypatch, [powershell], is_tty=True, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'terminal', 'source': 'powershell'
    }

    _prepare(monkeypatch, [], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'detached', 'source': 'detached_process'
    }


def test_interactive_tty_without_known_shell_is_still_terminal(monkeypatch):
    parent = _FakeParent('custom-launcher', '/opt/custom-launcher', ('custom-launcher',))
    _prepare(monkeypatch, [parent], is_tty=True)
    assert ClientInfoBuilder._detect_launch_context('linux') == {'mode': 'terminal', 'source': ''}


def test_systemd_user_and_system_services(monkeypatch):
    systemd_user = _FakeParent('systemd', '/usr/lib/systemd/systemd', ('systemd', '--user'))
    _prepare(monkeypatch, [systemd_user], is_tty=False)
    assert ClientInfoBuilder._detect_launch_context('linux') == {
        'mode': 'user_service', 'source': 'systemd_user'
    }

    systemd = _FakeParent('systemd', '/usr/lib/systemd/systemd', ('/sbin/init',))
    _prepare(monkeypatch, [systemd], is_tty=False)
    assert ClientInfoBuilder._detect_launch_context('linux') == {
        'mode': 'system_service', 'source': 'systemd'
    }


def test_windows_service_and_unknown(monkeypatch):
    services = _FakeParent('services.exe', r'C:\Windows\System32\services.exe', ('services.exe',))
    _prepare(monkeypatch, [services], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'system_service', 'source': 'windows_service'
    }

    parent = _FakeParent('custom-launcher', '/opt/custom-launcher', ('custom-launcher',))
    _prepare(monkeypatch, [parent], is_tty=False)
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 1234)
    monkeypatch.setattr(launch_context.os, 'getsid', lambda _pid: 1000)
    assert ClientInfoBuilder._detect_launch_context('linux') == {'mode': 'unknown', 'source': ''}


def test_pythonista_is_reported_as_ide(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False)
    assert ClientInfoBuilder._detect_launch_context('ios') == {'mode': 'ide', 'source': 'pythonista'}


def test_launch_context_is_cached_for_the_process(monkeypatch):
    monkeypatch.setattr(client_info_builder, '_LAUNCH_CONTEXT', None)
    monkeypatch.setattr(
        ClientInfoBuilder,
        '_detect_launch_context',
        staticmethod(lambda _os_alias: {'mode': 'terminal', 'source': 'zsh'}),
    )
    first = ClientInfoBuilder._get_launch_context('mac')
    monkeypatch.setattr(
        ClientInfoBuilder,
        '_detect_launch_context',
        staticmethod(lambda _os_alias: {'mode': 'unknown', 'source': ''}),
    )
    second = ClientInfoBuilder._get_launch_context('mac')
    assert first == second == {'mode': 'terminal', 'source': 'zsh'}

def test_client_info_build_reports_launch_snapshot(monkeypatch):
    identity = SimpleNamespace(
        os_alias='mac', os_type='macOS', os_full='macOS test', os_name='macOS',
        os_version='15.0', arch='arm64', manufacturer='Apple', model='Mac',
        hostname='host', machine_id='machine', fingerprint_basis='basis',
    )
    monkeypatch.setattr(client_info_builder, 'get_local_identity', lambda: identity)
    monkeypatch.setattr(client_info_builder, '_get_client_revision_manifest', lambda: {
        'revision': 'rev', 'parts': {}, 'files': {},
    })
    monkeypatch.setattr(client_info_builder, 'get_executable_path', lambda: 'python3 rchclient.py')
    monkeypatch.setattr(client_info_builder, 'get_client_log_path', lambda: '/tmp/client.log')
    monkeypatch.setattr(client_info_builder, 'check_privilege', lambda: 'user')
    monkeypatch.setattr(client_info_builder, 'get_system_paths', lambda: {})
    monkeypatch.setattr(ClientInfoBuilder, '_get_launch_context', classmethod(
        lambda cls, _os_alias: {'mode': 'ide', 'source': 'pycharm'}
    ))
    monkeypatch.setattr(ClientInfoBuilder, '_build_process_info', lambda self, _os_alias: {
        'username': 'alice', 'process_name': 'python3',
    })

    info = ClientInfoBuilder('client-1').build()
    assert info['launch_mode'] == 'ide'
    assert info['launch_source'] == 'pycharm'


def test_server_connection_payload_exposes_launch_snapshot():
    extras = {
        'python_ver': '3.12',
        'process_id': 123,
        'launch_command': 'python3 rchclient.py',
        'launch_mode': 'user_service',
        'launch_source': 'launchagent',
    }
    info = SimpleNamespace(
        client_id='client-1', addr='127.0.0.1', hostname='host', machine_id='machine',
        machine_fingerprint_basis='basis', os_type='macOS', os_alias='mac', os_ver='15.0',
        os_name='macOS', os_full='macOS test', arch='arm64', manufacturer='Apple', model='Mac',
        integrity='user', cwd='/tmp', build_version='dev', client_revision='',
        client_revision_parts={},
        get_extra=lambda key, default=None: extras.get(key, default),
    )
    context = SimpleNamespace(
        connected_at='2026-10-26T15:00:00', disconnected_at='', last_seen_at='',
        last_heartbeat_sent_at='', last_heartbeat_ack_at='', last_rtt_ms=None,
    )
    session = SimpleNamespace(session_info=info, context=context)
    service = WebConnectionService(SimpleNamespace(), SimpleNamespace(), None)

    payload = service.serialize_connection(session)
    assert payload['launch_mode'] == 'user_service'
    assert payload['launch_source'] == 'launchagent'

def test_recent_device_uses_latest_launch_snapshot_without_old_source_leak(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = RecentDeviceStore(db)
    base = {
        'machine_id': 'machine-1', 'client_id': 'client-1', 'hostname': 'host',
        'connection_state': 'online', 'launch_mode': 'ide', 'launch_source': 'pycharm',
    }
    store.upsert_from_connection(base)
    store.upsert_from_connection({
        **base,
        'client_id': 'client-2',
        'launch_mode': 'unknown',
        'launch_source': '',
    })

    item = store.list_recent_devices()[0]
    assert item['launch_mode'] == 'unknown'
    assert item['launch_source'] == ''
    db.close_thread_connection()

