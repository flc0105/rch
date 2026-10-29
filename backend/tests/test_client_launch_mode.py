from dataclasses import dataclass
from types import SimpleNamespace

import psutil
import pytest

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



def test_launchd_watchdog_policy_uses_explicit_launch_shape(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False, platform='linux')
    monkeypatch.setenv(launch_context.LAUNCH_MODE_ENV, 'user_service')
    monkeypatch.setenv(launch_context.LAUNCH_SOURCE_ENV, 'launchagent')
    assert launch_context.is_launchd_managed_client() is True

    monkeypatch.setenv(launch_context.LAUNCH_SOURCE_ENV, 'systemd_user')
    assert launch_context.is_launchd_managed_client() is False

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



def test_macos_elevated_command_keeps_default_and_adds_detached_option():
    from client.commands.platform.mac import MacCommands

    calls = []
    command = SimpleNamespace(
        mac_automation=SimpleNamespace(
            sudo_self=lambda *, detached=False: calls.append(detached) or (1, 'ok')
        )
    )

    assert MacCommands.spawn_elevated_instance(command, '--no-confirm') == (1, 'ok')
    assert calls.pop() is False
    assert MacCommands.spawn_elevated_instance(command, '--detached --no-confirm') == (1, 'ok')
    assert calls.pop() is True
    assert MacCommands.spawn_elevated_instance(command, '--bad --no-confirm') == (
        0,
        'Usage: spawn_elevated_instance [--detached] [--no-confirm]',
    )


def test_macos_elevated_detached_uses_short_lived_bootstrap(monkeypatch):
    import client.commands.platform.services.mac.automation_service as automation_service

    captured = []
    monkeypatch.setattr(
        automation_service,
        'get_executable_path',
        lambda: '/usr/bin/python3 /tmp/rchclient.py',
    )
    monkeypatch.setattr(
        automation_service.subprocess,
        'Popen',
        lambda *args, **kwargs: captured.append((args, kwargs)) or SimpleNamespace(pid=4321),
    )

    service = automation_service.MacAutomationService(SimpleNamespace())
    status, text = service.sudo_self(detached=False)
    assert status == 1
    assert 'parent PID: 4321' in text
    legacy_args, legacy_kwargs = captured.pop()
    assert '--elevated-detached-bootstrap' not in legacy_args[0][-1]
    assert 'start_new_session' not in legacy_kwargs

    status, text = service.sudo_self(detached=True)
    assert status == 1
    assert 'bootstrap PID: 4321' in text
    detached_args, detached_kwargs = captured.pop()
    assert '--elevated-detached-bootstrap' in detached_args[0][-1]
    assert detached_kwargs['start_new_session'] is True
    assert detached_kwargs['stdin'] is automation_service.subprocess.DEVNULL


def test_elevated_detached_bootstrap_removes_internal_flag_before_spawn(monkeypatch):
    import rchclient
    import client.runtime.client_util as runtime_client_util

    calls = []
    monkeypatch.setattr(rchclient.sys, 'argv', [
        '/tmp/rchclient.py', '--elevated-detached-bootstrap',
    ])
    monkeypatch.setattr(
        runtime_client_util,
        'spawn_new_instance',
        lambda: calls.append(tuple(rchclient.sys.argv)) or SimpleNamespace(pid=9876),
    )

    rchclient._run_elevated_detached_bootstrap()

    assert calls == [('/tmp/rchclient.py',)]



def _make_launchd_manager(monkeypatch, tmp_path, *, kind='agent', scope='user'):
    import client.runtime.launchd_service_manager as launchd_manager

    plist_dir = tmp_path / ('LaunchAgents' if kind == 'agent' else 'LaunchDaemons')
    log_dir = tmp_path / 'Logs'
    target = launchd_manager.LaunchdTarget(
        kind=kind,
        scope=scope if kind == 'agent' else 'system',
        label=launchd_manager.DEFAULT_LAUNCHD_LABEL,
        plist_path=str(plist_dir / f'{launchd_manager.DEFAULT_LAUNCHD_LABEL}.plist'),
        domain='gui/501' if kind == 'agent' else 'system',
        service_target=(
            f'gui/501/{launchd_manager.DEFAULT_LAUNCHD_LABEL}'
            if kind == 'agent'
            else f'system/{launchd_manager.DEFAULT_LAUNCHD_LABEL}'
        ),
        uid=501 if kind == 'agent' else 0,
        gid=20 if kind == 'agent' else 0,
        username='alice' if kind == 'agent' else 'root',
        home='/Users/alice' if kind == 'agent' else '/var/root',
        log_dir=str(log_dir),
    )
    monkeypatch.setattr(launchd_manager.sys, 'platform', 'darwin')
    monkeypatch.setattr(launchd_manager, 'resolve_launchd_target', lambda **_kwargs: target)
    monkeypatch.setattr(
        launchd_manager,
        'get_executable_path',
        lambda: '/usr/bin/python3 /tmp/rchclient.py',
    )
    monkeypatch.setattr(launchd_manager, 'get_runtime_root', lambda: '/tmp')
    manager = launchd_manager.LaunchdServiceManager(
        kind=kind,
        scope=scope,
        keep_alive=True,
    )
    return launchd_manager, manager, target


def test_launchd_targets_use_canonical_label_and_explicit_domains(monkeypatch):
    import client.runtime.launchd_service_manager as launchd_manager
    from client.runtime.user_identity import PosixUserIdentity

    alice = PosixUserIdentity(uid=501, gid=20, username='alice', home='/Users/alice')
    root = PosixUserIdentity(uid=0, gid=0, username='root', home='/var/root')
    monkeypatch.setattr(
        launchd_manager,
        'resolve_macos_target_user_identity',
        lambda _target=None: alice,
    )
    monkeypatch.setattr(
        launchd_manager,
        'get_posix_user_identity',
        lambda value=None: root if str(value) == '0' else alice,
    )

    agent = launchd_manager.resolve_launchd_target(kind='agent')
    assert agent.label == 'com.rch.client'
    assert agent.plist_path == '/Users/alice/Library/LaunchAgents/com.rch.client.plist'
    assert agent.domain == 'gui/501'
    assert agent.service_target == 'gui/501/com.rch.client'

    global_agent = launchd_manager.resolve_launchd_target(kind='agent', scope='global')
    assert global_agent.plist_path == '/Library/LaunchAgents/com.rch.client.plist'
    assert global_agent.domain == 'gui/501'

    daemon = launchd_manager.resolve_launchd_target(kind='daemon')
    assert daemon.plist_path == '/Library/LaunchDaemons/com.rch.client.plist'
    assert daemon.domain == 'system'
    assert daemon.service_target == 'system/com.rch.client'


def test_launchd_install_only_installs_definition_and_sets_launch_shape(monkeypatch, tmp_path):
    import plistlib

    launchd_manager, manager, target = _make_launchd_manager(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(launchd_manager.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(launchd_manager.os, 'chown', lambda *_args: None)

    def fake_launchctl(*args, check):
        calls.append(args)
        if args[0] == 'print':
            return SimpleNamespace(returncode=1, stdout='', stderr='not found')
        raise AssertionError(f'unexpected launchctl call during install: {args}')

    monkeypatch.setattr(manager, '_run_launchctl', fake_launchctl)
    result = manager.install()

    assert result['installed'] is True
    assert result['loaded'] is False
    assert calls == [('print', target.service_target), ('print', target.service_target)]

    with open(target.plist_path, 'rb') as file_obj:
        payload = plistlib.load(file_obj)
    assert payload['Label'] == 'com.rch.client'
    assert payload['ProgramArguments'] == ['/usr/bin/python3', '/tmp/rchclient.py']
    assert payload['RunAtLoad'] is True
    assert payload['KeepAlive'] is True
    assert payload['EnvironmentVariables'][launch_context.LAUNCH_MODE_ENV] == 'user_service'
    assert payload['EnvironmentVariables'][launch_context.LAUNCH_SOURCE_ENV] == 'launchagent'
    assert '/bin/sh' not in payload['ProgramArguments']


def test_launchd_plist_exposes_run_at_load_independently_from_keep_alive(monkeypatch, tmp_path):
    import plistlib

    launchd_manager, _manager, target = _make_launchd_manager(monkeypatch, tmp_path)
    manager = launchd_manager.LaunchdServiceManager(
        kind='agent',
        keep_alive=False,
        run_at_load=False,
    )
    monkeypatch.setattr(launchd_manager.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(launchd_manager.os, 'chown', lambda *_args: None)
    monkeypatch.setattr(
        manager,
        '_run_launchctl',
        lambda *args, check: SimpleNamespace(returncode=1, stdout='', stderr='not found'),
    )

    manager.install()

    with open(target.plist_path, 'rb') as file_obj:
        payload = plistlib.load(file_obj)
    assert payload['RunAtLoad'] is False
    assert payload['KeepAlive'] is False


def test_launchd_start_stop_restart_use_bootstrap_bootout_and_kickstart(monkeypatch, tmp_path):
    launchd_manager, manager, target = _make_launchd_manager(monkeypatch, tmp_path)
    monkeypatch.setattr(launchd_manager.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(launchd_manager.os, 'chown', lambda *_args: None)
    target_path = tmp_path / 'LaunchAgents' / 'com.rch.client.plist'
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b'plist')

    state = {'loaded': False, 'pid': None}
    calls = []

    def fake_launchctl(*args, check):
        calls.append(args)
        command = args[0]
        if command == 'print':
            if state['loaded']:
                return SimpleNamespace(
                    returncode=0,
                    stdout=f'state = running\npid = {state["pid"]}\n',
                    stderr='',
                )
            return SimpleNamespace(returncode=1, stdout='', stderr='not found')
        if command == 'bootstrap':
            assert args == ('bootstrap', target.domain, target.plist_path)
            state.update(loaded=True, pid=101)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if command == 'kickstart':
            state.update(loaded=True, pid=(state['pid'] or 100) + 1)
            return SimpleNamespace(returncode=0, stdout=str(state['pid']), stderr='')
        if command == 'bootout':
            assert args == ('bootout', target.service_target)
            state.update(loaded=False, pid=None)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(args)

    monkeypatch.setattr(manager, '_run_launchctl', fake_launchctl)

    started = manager.start()
    assert started['loaded'] is True and started['running'] is True
    assert ('bootstrap', target.domain, target.plist_path) in calls
    assert ('kickstart', '-p', target.service_target) in calls

    stopped = manager.stop()
    assert stopped['installed'] is True
    assert stopped['loaded'] is False and stopped['running'] is False
    assert ('bootout', target.service_target) in calls

    calls.clear()
    restarted = manager.restart()
    assert restarted['loaded'] is True and restarted['running'] is True
    assert ('bootstrap', target.domain, target.plist_path) in calls
    assert ('kickstart', '-p', target.service_target) in calls

    calls.clear()
    restarted = manager.restart()
    assert restarted['loaded'] is True
    assert ('kickstart', '-kp', target.service_target) in calls
    assert not any(call[0] in {'load', 'unload'} for call in calls)


def test_launchd_install_replaces_loaded_definition_but_does_not_restart(monkeypatch, tmp_path):
    launchd_manager, manager, target = _make_launchd_manager(monkeypatch, tmp_path)
    monkeypatch.setattr(launchd_manager.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(launchd_manager.os, 'chown', lambda *_args: None)
    state = {'loaded': True}
    calls = []

    def fake_launchctl(*args, check):
        calls.append(args)
        if args[0] == 'print':
            if state['loaded']:
                return SimpleNamespace(returncode=0, stdout='state = running\npid = 77\n', stderr='')
            return SimpleNamespace(returncode=1, stdout='', stderr='not found')
        if args[0] == 'bootout':
            state['loaded'] = False
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(args)

    monkeypatch.setattr(manager, '_run_launchctl', fake_launchctl)
    result = manager.install()
    assert result['installed'] is True and result['loaded'] is False
    assert ('bootout', target.service_target) in calls
    assert not any(call[0] in {'bootstrap', 'kickstart'} for call in calls)


def test_launchd_uninstall_stops_loaded_service_and_removes_plist(monkeypatch, tmp_path):
    launchd_manager, manager, target = _make_launchd_manager(monkeypatch, tmp_path)
    monkeypatch.setattr(launchd_manager.os, 'geteuid', lambda: 0)
    target_path = tmp_path / 'LaunchAgents' / 'com.rch.client.plist'
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b'plist')
    state = {'loaded': True}
    calls = []

    def fake_launchctl(*args, check):
        calls.append(args)
        if args[0] == 'print':
            if state['loaded']:
                return SimpleNamespace(returncode=0, stdout='state = running\npid = 88\n', stderr='')
            return SimpleNamespace(returncode=1, stdout='', stderr='not found')
        if args[0] == 'bootout':
            state['loaded'] = False
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(args)

    monkeypatch.setattr(manager, '_run_launchctl', fake_launchctl)
    result = manager.uninstall()
    assert result['installed'] is False and result['loaded'] is False
    assert not target_path.exists()
    assert ('bootout', target.service_target) in calls


def test_launchd_public_actions_include_start_and_stop_without_load_unload():
    import client.runtime.launchd_service_manager as launchd_manager
    assert launchd_manager.VALID_LAUNCHD_ACTIONS == {
        'install', 'start', 'stop', 'restart', 'uninstall', 'status',
    }



def test_macos_target_user_resolution_uses_effective_or_sudo_user(monkeypatch):
    import client.runtime.user_identity as user_identity

    records = {
        0: SimpleNamespace(pw_uid=0, pw_gid=0, pw_name='root', pw_dir='/var/root'),
        501: SimpleNamespace(pw_uid=501, pw_gid=20, pw_name='flc', pw_dir='/Users/flc'),
    }
    names = {'root': records[0], 'flc': records[501]}
    fake_pwd = SimpleNamespace(
        getpwuid=lambda uid: records[int(uid)],
        getpwnam=lambda name: names[str(name)],
    )
    monkeypatch.setattr(user_identity, '_pwd_module', lambda: fake_pwd)

    monkeypatch.setattr(user_identity.os, 'geteuid', lambda: 501)
    monkeypatch.delenv('SUDO_UID', raising=False)
    monkeypatch.delenv('SUDO_USER', raising=False)
    identity = user_identity.resolve_macos_target_user_identity()
    assert (identity.uid, identity.home) == (501, '/Users/flc')

    monkeypatch.setattr(user_identity.os, 'geteuid', lambda: 0)
    monkeypatch.setenv('SUDO_UID', '501')
    monkeypatch.setenv('SUDO_USER', 'flc')
    identity = user_identity.resolve_macos_target_user_identity()
    assert (identity.username, identity.home) == ('flc', '/Users/flc')


def test_macos_target_user_resolution_falls_back_to_console_user(monkeypatch):
    import client.runtime.user_identity as user_identity

    console = user_identity.PosixUserIdentity(
        uid=502, gid=20, username='desktop', home='/Users/desktop',
    )
    monkeypatch.setattr(user_identity.os, 'geteuid', lambda: 0)
    monkeypatch.delenv('SUDO_UID', raising=False)
    monkeypatch.delenv('SUDO_USER', raising=False)
    monkeypatch.setattr(user_identity, 'get_macos_console_user_identity', lambda: console)
    identity = user_identity.resolve_macos_target_user_identity()
    assert identity == console


def test_launchd_script_sdk_exposes_canonical_actions():
    from client.runtime.sdk import launchd

    assert launchd.DEFAULT_LAUNCHD_LABEL == 'com.rch.client'
    assert launchd.VALID_LAUNCHD_ACTIONS == {
        'install', 'start', 'stop', 'restart', 'uninstall', 'status',
    }


def test_client_info_reports_watchdog_effective_state_for_launchd(monkeypatch):
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
        lambda cls, _os_alias: {'mode': 'user_service', 'source': 'launchagent'}
    ))
    monkeypatch.setattr(ClientInfoBuilder, '_build_process_info', lambda self, _os_alias: {
        'username': 'alice', 'process_name': 'python3',
    })

    info = ClientInfoBuilder('client-launchd').build()
    assert 'remote_watchdog_enabled' not in info
    assert 'local_watchdog_enabled' not in info
    assert info['feature_manifest']['watchdog'] is True


def test_windows_powershell_bootstrap_not_confused_with_ancestor_services(monkeypatch):
    _prepare(monkeypatch, [
        _FakeParent('powershell.exe', r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'),
        _FakeParent('services.exe', r'C:\Windows\System32\services.exe'),
    ], is_tty=True, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('windows') == {'mode': 'terminal', 'source': 'powershell'}

    _prepare(monkeypatch, [_FakeParent('services.exe', r'C:\Windows\System32\services.exe')], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('windows') == {'mode': 'system_service', 'source': 'windows_service'}


def test_windows_bootstrap_sets_detached_launch_mode_for_start_process():
    from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService
    script = AgentBootstrapScriptService().generate_powershell_script({
        'server_host': '127.0.0.1', 'server_port': 8787, 'web_port': 8085,
    })
    assert "$env:RCH_CLIENT_LAUNCH_MODE = 'detached'" in script
    assert "$env:RCH_CLIENT_LAUNCH_SOURCE = 'detached_process'" in script
    assert 'try {' in script and '} finally {' in script
    assert 'try {{' not in script
    assert 'Start-Process -FilePath $py' in script
