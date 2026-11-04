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
    process_id: int = 0

    @property
    def pid(self):
        return self.process_id

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


def test_detached_session_outweighs_inherited_pycharm_context(monkeypatch):
    pycharm = _FakeParent('pycharm', '/Applications/PyCharm.app/Contents/MacOS/pycharm', ('pycharm',))
    _prepare(monkeypatch, [pycharm], is_tty=False, platform='darwin')
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 1234)
    monkeypatch.setattr(launch_context.os, 'getsid', lambda _pid: 1234)
    # A detached child can inherit the IDE's environment without being hosted by it.
    monkeypatch.setenv('PYCHARM_HOSTED', '1')
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'detached', 'source': 'new_session'
    }



def test_launchd_management_requires_live_job_not_environment(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False, platform='darwin')
    monkeypatch.setattr(launch_context, '_verified_launchd_job_for_pid', lambda _pid: None)
    assert launch_context.is_launchd_managed_client() is False

    monkeypatch.setattr(launch_context, '_verified_launchd_job_for_pid', lambda _pid: {
        'mode': 'user_service', 'source': 'launchagent',
    })
    assert launch_context.is_launchd_managed_client() is True

def test_spawn_new_instance_marks_the_new_client_as_detached(monkeypatch):
    captured = {}
    monkeypatch.setattr(client_util.os, 'name', 'posix')
    monkeypatch.setattr(client_util, 'get_executable_argv', lambda: ['python3', '/tmp/rchclient.py'])
    monkeypatch.setattr(client_util.sys, 'argv', ['/tmp/rchclient.py'])
    monkeypatch.setattr(client_util.subprocess, 'Popen', lambda *args, **kwargs: captured.update({
        'args': args, 'kwargs': kwargs,
    }) or SimpleNamespace(pid=1234))

    client_util.spawn_new_instance()

    env = captured['kwargs']['env']
    assert 'RCH_CLIENT_LAUNCH_MODE' not in env
    assert 'RCH_CLIENT_LAUNCH_SOURCE' not in env
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


def test_macos_launchagent_and_launchdaemon_require_verified_job(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False, platform='darwin')
    monkeypatch.setenv('XPC_SERVICE_NAME', 'com.example.rch.agent')
    monkeypatch.setattr(launch_context, '_verified_launchd_job_for_pid', lambda _pid: None)
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 1234)
    monkeypatch.setattr(launch_context.os, 'getsid', lambda _pid: 1234)
    launchd = _FakeParent('launchd', '/sbin/launchd', ('/sbin/launchd',))
    monkeypatch.setattr(psutil, 'Process', lambda: _FakeProcess([launchd]))
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'detached', 'source': 'new_session',
    }

    monkeypatch.setattr(launch_context, '_verified_launchd_job_for_pid', lambda _pid: {
        'mode': 'user_service', 'source': 'launchagent',
    })
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'user_service', 'source': 'launchagent',
    }
    monkeypatch.setattr(launch_context, '_verified_launchd_job_for_pid', lambda _pid: {
        'mode': 'system_service', 'source': 'launchdaemon',
    })
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'system_service', 'source': 'launchdaemon',
    }


def test_macos_go_loader_orphan_without_launch_marker_is_detached(monkeypatch):
    launchd = _FakeParent('launchd', '/sbin/launchd', ('/sbin/launchd',))
    _prepare(monkeypatch, [launchd], is_tty=False, platform='darwin')
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 4290)
    monkeypatch.setattr(launch_context.os, 'getsid', lambda _pid: 4290)
    monkeypatch.setattr(launch_context, '_verified_launchd_job_for_pid', lambda _pid: None)
    assert ClientInfoBuilder._detect_launch_context('mac') == {
        'mode': 'detached', 'source': 'new_session',
    }


def test_launchctl_verifies_running_job_pid_and_type(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False, platform='darwin')
    monkeypatch.setattr(launch_context.os, 'getuid', lambda: 501)
    launch_context._verified_launchd_job_for_pid.cache_clear()
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1] == 'list':
            return SimpleNamespace(returncode=0, stdout='PID Status Label\n1234 0 com.rch.client\n')
        if args[2] == 'gui/501/com.rch.client':
            return SimpleNamespace(returncode=0, stdout='state = running\npid = 1234\ntype = LaunchAgent\n')
        return SimpleNamespace(returncode=1, stdout='')

    monkeypatch.setattr(launch_context.subprocess, 'run', fake_run)
    try:
        assert launch_context._verified_launchd_job_for_pid(1234) == {
            'mode': 'user_service', 'source': 'launchagent',
        }
        assert ['/bin/launchctl', 'print', 'gui/501/com.rch.client'] in calls
    finally:
        launch_context._verified_launchd_job_for_pid.cache_clear()


@pytest.mark.parametrize('list_line,detail', [
    ('1234 0 0x123.anonymous.python', 'state = running\npid = 1234\ntype = LaunchAgent'),
    ('1234 0 com.rch.client', 'state = running\npid = 9999\ntype = LaunchAgent'),
    ('1234 0 com.rch.client', 'state = waiting\npid = 1234\ntype = LaunchAgent'),
    ('1234 0 com.rch.client', 'state = running\npid = 1234\ntype = Other'),
    ('9999 0 com.rch.client', 'state = running\npid = 1234\ntype = LaunchAgent'),
])
def test_launchctl_rejects_unverified_or_anonymous_pid(monkeypatch, list_line, detail):
    _prepare(monkeypatch, [], is_tty=False, platform='darwin')
    monkeypatch.setattr(launch_context.os, 'getuid', lambda: 501)
    launch_context._verified_launchd_job_for_pid.cache_clear()

    def fake_run(args, **kwargs):
        if args[1] == 'list':
            return SimpleNamespace(returncode=0, stdout='PID Status Label\n' + list_line)
        return SimpleNamespace(returncode=0, stdout=detail)

    monkeypatch.setattr(launch_context.subprocess, 'run', fake_run)
    try:
        assert launch_context._verified_launchd_job_for_pid(1234) is None
    finally:
        launch_context._verified_launchd_job_for_pid.cache_clear()


def test_launchctl_system_daemon_matches_exact_job_pid(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False, platform='darwin')
    monkeypatch.setattr(launch_context.os, 'getuid', lambda: 0)
    launch_context._verified_launchd_job_for_pid.cache_clear()

    def fake_run(args, **kwargs):
        if args[1] == 'list':
            return SimpleNamespace(returncode=0, stdout='PID Status Label\n4421 0 com.rch.client')
        if args[2] == 'system/com.rch.client':
            return SimpleNamespace(returncode=0, stdout='state = running\npid = 4421\ntype = LaunchDaemon')
        return SimpleNamespace(returncode=1, stdout='')

    monkeypatch.setattr(launch_context.subprocess, 'run', fake_run)
    try:
        assert launch_context._verified_launchd_job_for_pid(4421) == {
            'mode': 'system_service', 'source': 'launchdaemon',
        }
    finally:
        launch_context._verified_launchd_job_for_pid.cache_clear()


def test_macos_unmanaged_no_tty_non_leader_is_detached(monkeypatch):
    _prepare(monkeypatch, [], is_tty=False, platform='darwin')
    monkeypatch.setattr(launch_context, '_verified_launchd_job_for_pid', lambda _pid: None)
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 5011)
    monkeypatch.setattr(launch_context.os, 'getsid', lambda _pid: 5000)

    class ProcessWithNoTty(_FakeProcess):
        def terminal(self):
            return None

    monkeypatch.setattr(psutil, 'Process', lambda: ProcessWithNoTty([]))
    assert ClientInfoBuilder._detect_launch_context('mac') == {'mode': 'detached', 'source': ''}


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



def test_windows_task_scheduler_svchost_launch_is_scheduled(monkeypatch):
    cmd = _FakeParent('cmd.exe', r'C:\Windows\System32\cmd.exe', ('cmd.exe', '/c', 'python', 'rchclient.py'))
    schedule_host = _FakeParent('svchost.exe', r'C:\Windows\System32\svchost.exe',
                                ('svchost.exe', '-k', 'netsvcs', '-p', '-s', 'Schedule'),
                                process_id=970)
    _prepare(monkeypatch, [cmd, schedule_host], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('windows') == {
        'mode': 'scheduled', 'source': 'schtasks',
    }


def test_windows_task_scheduler_service_pid_matches_shared_host(monkeypatch):
    import psutil
    cmd = _FakeParent('powershell.exe', r'C:\Windows\System32\WindowsPowerShell\powershell.exe')
    schedule_host = _FakeParent('svchost.exe', r'C:\Windows\System32\svchost.exe',
                                ('svchost.exe', '-k', 'netsvcs'), process_id=551)
    _prepare(monkeypatch, [cmd, schedule_host], is_tty=False, platform='win32')
    monkeypatch.setattr(psutil, 'win_service_get', lambda _name: SimpleNamespace(
        as_dict=lambda: {'pid': 551},
    ), raising=False)
    assert ClientInfoBuilder._detect_launch_context('windows') == {
        'mode': 'scheduled', 'source': 'schtasks',
    }


def test_windows_unrelated_svchost_not_assumed_scheduled(monkeypatch):
    import psutil
    powershell = _FakeParent('powershell.exe', 'powershell.exe')
    other_host = _FakeParent('svchost.exe', r'C:\Windows\System32\svchost.exe',
                             ('svchost.exe', '-k', 'netsvcs'), process_id=551)
    _prepare(monkeypatch, [powershell, other_host], is_tty=False, platform='win32')
    monkeypatch.setattr(psutil, 'win_service_get', lambda _name: SimpleNamespace(
        as_dict=lambda: {'pid': 552},
    ), raising=False)
    assert ClientInfoBuilder._detect_launch_context('windows') == {
        'mode': 'detached', 'source': 'detached_process',
    }

def test_windows_terminal_and_detached_modes(monkeypatch):
    powershell = _FakeParent(
        'powershell.exe',
        r'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
        ('powershell.exe',),
    )
    import ctypes
    kernel = SimpleNamespace(GetConsoleProcessList=lambda _ids, _length: 1)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=kernel), raising=False)
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
    _prepare(monkeypatch, [_FakeParent('systemd')], is_tty=False)
    monkeypatch.setattr(launch_context, '_verified_systemd_unit_for_pid', lambda pid: {
        'mode': 'user_service', 'source': 'systemd_user',
    })
    assert ClientInfoBuilder._detect_launch_context('linux') == {
        'mode': 'user_service', 'source': 'systemd_user'
    }
    monkeypatch.setattr(launch_context, '_verified_systemd_unit_for_pid', lambda pid: {
        'mode': 'system_service', 'source': 'systemd',
    })
    assert ClientInfoBuilder._detect_launch_context('linux') == {
        'mode': 'system_service', 'source': 'systemd'
    }


def test_linux_does_not_trust_inherited_systemd_markers_or_parent(monkeypatch):
    _prepare(monkeypatch, [_FakeParent('systemd')], is_tty=False)
    monkeypatch.setenv('INVOCATION_ID', 'pretend-service')
    monkeypatch.setattr(launch_context, '_verified_systemd_unit_for_pid', lambda pid: None)
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 111)
    monkeypatch.setattr(launch_context.os, 'getsid', lambda _pid: 123)
    assert ClientInfoBuilder._detect_launch_context('linux') == {
        'mode': 'unknown', 'source': ''
    }


def test_linux_systemd_requires_active_unit_and_exact_main_pid(monkeypatch):
    import builtins
    import io
    _prepare(monkeypatch, [], is_tty=False)
    monkeypatch.setattr(launch_context.sys, 'platform', 'linux')
    native_open = builtins.open
    cgroup = {'content': '0::/user.slice/user-1000.slice/user@1000.service/app.slice/rch-agent.service\n'}
    def fake_open(path, *args, **kwargs):
        if path == '/proc/4321/cgroup':
            return io.StringIO(cgroup['content'])
        return native_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', fake_open)
    calls = []
    props = {'text': 'ActiveState=active\nMainPID=4321\n'}
    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=props['text'])
    monkeypatch.setattr(launch_context.subprocess, 'run', fake_run)
    assert launch_context._verified_systemd_unit_for_pid(4321) == {
        'mode': 'user_service', 'source': 'systemd_user'
    }
    assert calls[-1] == ['systemctl', '--user', 'show', 'rch-agent.service',
                         '--property=MainPID', '--property=ActiveState']
    props['text'] = 'ActiveState=active\nMainPID=9999\n'
    assert launch_context._verified_systemd_unit_for_pid(4321) is None
    props['text'] = 'ActiveState=inactive\nMainPID=4321\n'
    assert launch_context._verified_systemd_unit_for_pid(4321) is None
    cgroup['content'] = '0::/system.slice/rch-agent.service\n'
    props['text'] = 'ActiveState=active\nMainPID=4321\n'
    assert launch_context._verified_systemd_unit_for_pid(4321) == {
        'mode': 'system_service', 'source': 'systemd'
    }
    assert calls[-1][0:3] == ['systemctl', 'show', 'rch-agent.service']
    cgroup['content'] = '0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-terminal.scope\n'
    assert launch_context._verified_systemd_unit_for_pid(4321) is None


def test_launch_mode_markers_never_override_observed_windows_or_linux_mode(monkeypatch):
    for platform, os_alias, parent, mode, source in (
        ('linux', 'linux', 'zsh', 'terminal', 'zsh'),
        ('win32', 'win', 'powershell.exe', 'terminal', 'powershell'),
    ):
        _prepare(monkeypatch, [_FakeParent(parent)], is_tty=True, platform=platform)
        monkeypatch.setenv('RCH_CLIENT_LAUNCH_MODE', 'system_service')
        monkeypatch.setenv('RCH_CLIENT_LAUNCH_SOURCE', 'forged')
        if platform == 'linux':
            monkeypatch.setattr(launch_context, '_verified_systemd_unit_for_pid', lambda pid: None)
        else:
            import ctypes
            monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=SimpleNamespace(
                GetConsoleProcessList=lambda _ids, _length: 1,
            )), raising=False)
        assert ClientInfoBuilder._detect_launch_context(os_alias) == {'mode': mode, 'source': source}


def test_windows_service_and_unknown(monkeypatch):
    services = _FakeParent('services.exe', r'C:\Windows\System32\services.exe', ('services.exe',))
    _prepare(monkeypatch, [services], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'detached', 'source': 'detached_process'
    }

    parent = _FakeParent('custom-launcher', '/opt/custom-launcher', ('custom-launcher',))
    _prepare(monkeypatch, [parent], is_tty=False)
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 1234)
    monkeypatch.setattr(launch_context.os, 'getsid', lambda _pid: 1000)
    assert ClientInfoBuilder._detect_launch_context('linux') == {'mode': 'unknown', 'source': ''}


def test_windows_scm_service_matching_exact_running_pid(monkeypatch):
    import psutil
    _prepare(monkeypatch, [_FakeParent('services.exe')], is_tty=False, platform='win32')
    monkeypatch.setattr(launch_context.os, 'getpid', lambda: 9876)
    entry = {'status': 'running', 'pid': 9876}
    monkeypatch.setattr(psutil, 'win_service_iter', lambda: [SimpleNamespace(
        as_dict=lambda: dict(entry),
    )], raising=False)
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'system_service', 'source': 'windows_service'
    }
    entry['pid'] = 9999
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'detached', 'source': 'detached_process'
    }
    entry['pid'] = 9876
    entry['status'] = 'stopped'
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'detached', 'source': 'detached_process'
    }


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




def test_windows_elevated_detached_and_cli_options():
    from client.commands.platform.win import WindowsCommands

    seen = []
    command = SimpleNamespace(win_privilege=SimpleNamespace(
        spawn_elevated_instance=lambda *, detached=False: seen.append(detached) or (1, 'ok'),
    ))
    assert WindowsCommands.spawn_elevated_instance(command, '--no-confirm') == (1, 'ok')
    assert seen.pop() is False
    assert WindowsCommands.spawn_elevated_instance(command, '--detached --no-confirm') == (1, 'ok')
    assert seen.pop() is True
    assert WindowsCommands.spawn_elevated_instance(command, '--bgrun --no-confirm') == (
        0, 'Usage: spawn_elevated_instance [--detached] [--no-confirm]',
    )
    assert WindowsCommands.spawn_elevated_instance(command, '--bad --no-confirm') == (
        0, 'Usage: spawn_elevated_instance [--detached] [--no-confirm]',
    )
    assert seen == []


def test_windows_detached_elevation_uses_native_create_process_flags(monkeypatch):
    import base64
    import ctypes
    import subprocess
    import sys
    from client.commands.platform.services.win.privilege_service import WinPrivilegeService

    calls = []
    shell = SimpleNamespace(ShellExecuteW=lambda *args: calls.append(args) or 42)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(shell32=shell), raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\Tools\Python 3.13\python.exe')
    monkeypatch.setattr(sys, 'argv', [r'C:\Program Files\RCH\rchclient.py', '--flag', "O'Brian value"])
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr('os.getcwd', lambda: r'C:\RCH Files')
    monkeypatch.setenv('SystemRoot', r'C:\Windows')

    assert WinPrivilegeService(None).spawn_elevated_instance(detached=True)[0] == 1
    _handle, verb, path, arguments, cwd, show = calls[0]
    assert verb == 'runas'
    assert path.endswith('WindowsPowerShell/v1.0/powershell.exe') or path.endswith(
        r'WindowsPowerShell\v1.0\powershell.exe')
    assert show == 0
    assert cwd == r'C:\RCH Files'
    assert '-WindowStyle Hidden -EncodedCommand ' in arguments
    encoded = arguments.split(' -EncodedCommand ', 1)[1]
    ps = base64.b64decode(encoded).decode('utf-16-le')
    assert 'CreateProcessW' in ps
    assert '0x208' in ps
    assert 'GetLastWin32Error' in ps
    assert 'RCH_CLIENT_LAUNCH_MODE' not in ps
    assert 'RCH_CLIENT_LAUNCH_SOURCE' not in ps
    assert "O''Brian" in ps
    assert r'C:\Program Files\RCH\rchclient.py' in ps
    assert r'C:\Tools\Python 3.13\python.exe' in ps
    assert 'RCH_PROCESS_RECOVERY_WATCHDOG_SESSION' in ps

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


def test_macos_elevation_uses_original_launch_command_without_client_bootstrap_flags(monkeypatch):
    import client.commands.platform.services.mac.automation_service as automation_service
    captured = []
    monkeypatch.setattr(
        automation_service, 'get_executable_path',
        lambda: '"/tmp/python with spaces" "/tmp/rchclient.py" --profile tls-local',
    )
    monkeypatch.setattr(
        automation_service.subprocess, 'run',
        lambda argv, **kwargs: captured.append((argv, kwargs)) or SimpleNamespace(
            returncode=0, stderr='', stdout='RCH_ELEVATED_CLIENT_PID=4321\n',
        ),
    )
    service = automation_service.MacAutomationService(SimpleNamespace())
    for detached in (False, True):
        status, message = service.sudo_self(detached=detached)
        assert status == 1
        assert 'PID: 4321' in message
        args, kwargs = captured.pop()
        assert args[:2] == ['osascript', '-e']
        assert chr(92) + '"/tmp/python with spaces' in args[2]
        assert '--profile tls-local' in args[2]
        assert '--elevated-bootstrap' not in args[2]
        assert '--elevated-detached-bootstrap' not in args[2]
        assert ('/usr/bin/perl -MPOSIX=setsid' in args[2]) is detached
        assert kwargs['capture_output'] is True


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
    assert 'EnvironmentVariables' not in payload
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
    assert 'remote_control_watchdog_enabled' not in info
    assert 'local_heartbeat_watchdog_enabled' not in info
    assert info['feature_manifest']['watchdog'] is True


def test_windows_powershell_bootstrap_not_confused_with_ancestor_services(monkeypatch):
    _prepare(monkeypatch, [
        _FakeParent('powershell.exe', r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'),
        _FakeParent('services.exe', r'C:\Windows\System32\services.exe'),
    ], is_tty=True, platform='win32')
    import ctypes
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=SimpleNamespace(
        GetConsoleProcessList=lambda _ids, _length: 1,
    )), raising=False)
    assert ClientInfoBuilder._detect_launch_context('windows') == {'mode': 'terminal', 'source': 'powershell'}

    _prepare(monkeypatch, [_FakeParent('services.exe', r'C:\Windows\System32\services.exe')], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('windows') == {'mode': 'detached', 'source': 'detached_process'}


def test_windows_bootstrap_launches_without_mode_environment():
    from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService
    script = AgentBootstrapScriptService().generate_powershell_script({
        'server_host': '127.0.0.1', 'server_port': 8787, 'web_port': 8085,
    })
    assert 'RCH_CLIENT_LAUNCH_MODE' not in script
    assert 'RCH_CLIENT_LAUNCH_SOURCE' not in script
    assert '& $py -c $launchCode $script' in script
    assert 'subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP' in script
    assert '$startInfo.CreateNoWindow' not in script
    assert 'try {{' not in script


def test_windows_detached_console_window_does_not_make_a_terminal(monkeypatch):
    """ConPTY / a hidden console host is not evidence of usable console I/O."""
    import ctypes

    def get_std_handle(_stream):
        return 123

    def get_console_mode(_handle, _mode):
        return 0

    kernel = SimpleNamespace(
        GetConsoleWindow=lambda: 123456,  # Not proof of console attachment.
        GetConsoleProcessList=lambda _ids, _length: 0,
        GetStdHandle=get_std_handle,
        GetConsoleMode=get_console_mode,
    )
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=kernel), raising=False)
    powershell = _FakeParent('powershell.exe', r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
    _prepare(monkeypatch, [powershell], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('windows') == {
        'mode': 'detached', 'source': 'detached_process',
    }
    _prepare(monkeypatch, [], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('windows') == {
        'mode': 'detached', 'source': 'detached_process',
    }


def test_windows_actual_console_std_handle_is_terminal(monkeypatch):
    import ctypes

    kernel = SimpleNamespace(
        GetConsoleWindow=lambda: 123456,
        GetConsoleProcessList=lambda _ids, _length: 1,
        GetStdHandle=lambda _stream: 123,
        GetConsoleMode=lambda _handle, _mode: 1,
    )
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=kernel), raising=False)
    _prepare(monkeypatch, [_FakeParent('cmd.exe')], is_tty=False, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'terminal', 'source': 'cmd',
    }


def test_windows_no_console_attachment_is_detached_despite_tty_and_inherited_handles(monkeypatch):
    import ctypes
    kernel = SimpleNamespace(
        GetConsoleWindow=lambda: 100,
        GetConsoleProcessList=lambda _ids, _length: 0,
        GetStdHandle=lambda _stream: 123,
        GetConsoleMode=lambda _handle, _mode: 1,
    )
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=kernel), raising=False)
    _prepare(monkeypatch, [_FakeParent('powershell.exe')], is_tty=True, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'detached', 'source': 'detached_process',
    }


def test_windows_console_query_unavailable_does_not_guess_terminal(monkeypatch):
    import ctypes
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=SimpleNamespace()), raising=False)
    _prepare(monkeypatch, [_FakeParent('cmd.exe')], is_tty=True, platform='win32')
    assert ClientInfoBuilder._detect_launch_context('win') == {
        'mode': 'detached', 'source': 'detached_process',
    }


def test_windows_duplicate_and_update_use_detached_process_flags(monkeypatch):
    import subprocess
    captured = []
    monkeypatch.setattr(client_util.os, 'name', 'nt')
    monkeypatch.setattr(subprocess, 'DETACHED_PROCESS', 0x8, raising=False)
    monkeypatch.setattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200, raising=False)
    monkeypatch.setattr(client_util.subprocess, 'Popen', lambda *a, **kw: captured.append((a, kw)) or SimpleNamespace(pid=12))
    client_util._spawn_new_instance_process(['python.exe', 'rchclient.py'], {}, True)
    monkeypatch.setattr(client_util, '_resolve_python_command_for_source_bundle', lambda: ['python.exe'])
    client_util.spawn_detached_python_script('rchclient.py')
    assert len(captured) == 2
    for _args, kwargs in captured:
        assert kwargs['creationflags'] == 0x208


def test_powershell_one_liner_really_detaches_using_windows_process_flags(monkeypatch):
    import re
    import subprocess
    import sys
    from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService

    script = AgentBootstrapScriptService().generate_powershell_script({
        'server_host': '127.0.0.1', 'server_port': 9999, 'web_port': 8085,
    })
    match = re.search(r"^\$launchCode = '([^'\r\n]+)'$", script, re.MULTILINE)
    assert match, 'one-liner must use a real detached process launcher'
    code = match.group(1)
    compile(code, '<powershell-detached-launcher>', 'exec')
    seen = []
    monkeypatch.setattr(subprocess, 'DETACHED_PROCESS', 0x8, raising=False)
    monkeypatch.setattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200, raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: seen.append((a, kw)) or SimpleNamespace(pid=345))
    monkeypatch.setattr(sys, 'argv', ['launcher', '/path with spaces/rchclient.py'])
    exec(code, {'__name__': '__main__'})
    assert len(seen) == 1
    args, kwargs = seen[0]
    assert args[0][1] == '/path with spaces/rchclient.py'
    assert kwargs['creationflags'] == 0x208
    assert kwargs['stdin'] == subprocess.DEVNULL
    assert kwargs['stdout'] == subprocess.DEVNULL
    assert kwargs['stderr'] == subprocess.DEVNULL
    assert '& $py -c $launchCode $script' in script
    assert '$startInfo.CreateNoWindow' not in script
    assert 'RCH_CLIENT_LAUNCH_MODE' not in script
