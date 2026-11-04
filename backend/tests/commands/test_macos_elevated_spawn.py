"""macOS elevated Client launcher: preserve original command and report real PID."""

import os
import subprocess
from types import SimpleNamespace

import pytest

from client.commands.platform.services.mac.automation_service import MacAutomationService
from client.runtime import client_util


def _service():
    return MacAutomationService(owner=None)


@pytest.mark.parametrize('detached', [False, True])
def test_sudo_self_returns_client_pid_and_preserves_tls_profile(monkeypatch, detached):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen['cmd'] = cmd
        seen['kwargs'] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout='RCH_ELEVATED_CLIENT_PID=37124\nRCH_ELEVATED_CLIENT_LOG=/tmp/rch-elevated-test.log\n',
            stderr='',
        )

    monkeypatch.setattr('client.commands.platform.services.mac.automation_service.subprocess.run', fake_run)
    monkeypatch.setattr('client.commands.platform.services.mac.automation_service.get_executable_path',
                        lambda: '"/tmp/python with spaces" /tmp/rchclient.py --profile tls-local')
    status, message = _service().sudo_self(detached=detached)
    assert status == 1
    assert 'PID: 37124' in message
    assert 'connection not yet verified' in message
    script = seen['cmd'][2]
    assert seen['cmd'][:2] == ['osascript', '-e']
    assert '"/tmp/python with spaces"' not in script  # AppleScript escaping
    assert r'\"/tmp/python with spaces\"' in script
    assert '--profile tls-local' in script
    assert '--elevated-bootstrap' not in script
    assert '--elevated-detached-bootstrap' not in script
    assert ('/usr/bin/perl -MPOSIX=setsid' in script) == detached
    assert seen['kwargs']['capture_output'] is True


@pytest.mark.parametrize('result,expected', [
    (SimpleNamespace(returncode=1, stderr='User cancelled. (-128)', stdout=''), 'cancelled'),
    (SimpleNamespace(returncode=0, stderr='', stdout='some other output'), 'no Client PID'),
])
def test_sudo_self_reports_authorization_and_missing_pid(monkeypatch, result, expected):
    monkeypatch.setattr('client.commands.platform.services.mac.automation_service.subprocess.run',
                        lambda *_a, **_kw: result)
    code, detail = _service().sudo_self()
    assert code == 0
    assert expected in detail


def test_sudo_self_reports_applescript_timeout(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(['osascript'], 120)
    monkeypatch.setattr('client.commands.platform.services.mac.automation_service.subprocess.run', timeout)
    code, detail = _service().sudo_self()
    assert code == 0
    assert 'failed' in detail.lower()


@pytest.mark.parametrize('detached', [False, True])
def test_elevated_shell_launch_execs_same_pid_and_preserves_args(monkeypatch, tmp_path, detached):
    """Exercise generated shell script without requesting OS elevation."""
    import shlex
    import client.commands.platform.services.mac.automation_service as automation_service

    # This small script stays alive long enough for the shell health check.
    script = tmp_path / 'agent demo.py'
    script.write_text('import os,sys,time\n'
                      'open(sys.argv[1],"w").write(str(os.getpid())+"\\n"+" ".join(sys.argv[2:]))\n'
                      'time.sleep(3)\n')
    output = tmp_path / 'child.pid'
    launcher_cmd = f'{shlex.quote(os.path.realpath(__import__("sys").executable))} {shlex.quote(str(script))} {shlex.quote(str(output))} --profile tls-local'
    monkeypatch.setattr(automation_service, 'get_executable_path', lambda: launcher_cmd)
    monkeypatch.setattr(automation_service, 'get_runtime_root', lambda: str(tmp_path))
    import re
    original_run = subprocess.run
    def fake_run(cmd, **kwargs):
        if cmd[:2] == ['osascript', '-e']:
            apple = cmd[2]
            match = re.fullmatch(r'do shell script "(.*)" with administrator privileges', apple)
            assert match
            inner = match.group(1).replace(chr(92) + '"', '"').replace(chr(92) * 2, chr(92))
            return original_run(['/bin/sh', '-c', inner], capture_output=True, text=True, timeout=8)
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(automation_service.subprocess, 'run', fake_run)
    try:
        result, message = _service().sudo_self(detached=detached)
        assert result == 1, message
        pid = int(re.search(r'PID: (\d+)', message).group(1))
        recorded = output.read_text().splitlines()
        assert int(recorded[0]) == pid
        assert recorded[1] == '--profile tls-local'
        if detached:
            assert os.getsid(pid) == pid
    finally:
        if output.exists():
            try:
                os.kill(int(output.read_text().splitlines()[0]), 15)
            except (OSError, ValueError):
                pass


def test_spawn_new_instance_preserves_argv_and_new_session(monkeypatch, tmp_path):
    seen = {}

    def fake_popen(command, **kwargs):
        seen['command'] = command
        seen['kwargs'] = kwargs
        return SimpleNamespace(pid=2468)

    import sys
    monkeypatch.setattr(client_util.subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(sys, 'argv', ['/tmp/RCH folder/rchclient.py', '--profile', 'tls-local'])
    stderr_file = tmp_path / 'spawn-error.log'
    child = client_util.spawn_new_instance(start_new_session=False, stderr_path=str(stderr_file))
    assert child.pid == 2468
    assert seen['command'] == [os.path.realpath(sys.executable), os.path.realpath(sys.argv[0]),
                               '--profile', 'tls-local']
    assert seen['kwargs']['start_new_session'] is False
    assert isinstance(seen['command'], list)
    assert seen['kwargs']['stderr'].closed
    assert stderr_file.is_file()


def test_spawn_new_instance_default_retains_detached_behavior(monkeypatch):
    seen = {}

    def fake_popen(command, **kwargs):
        seen['command'] = command
        seen['kwargs'] = kwargs
        return SimpleNamespace(pid=6543)

    import sys
    monkeypatch.setattr(client_util.subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(sys, 'argv', ['rchclient.py', '--profile', 'tls-local'])
    child = client_util.spawn_new_instance()
    assert child.pid == 6543
    assert seen['kwargs']['start_new_session'] is True
    assert seen['command'][-2:] == ['--profile', 'tls-local']


def test_elevated_shell_early_exit_is_reported_as_failure(monkeypatch, tmp_path):
    """The elevated request must not report success for a crashing Client."""
    import re
    import shlex
    import sys
    import client.commands.platform.services.mac.automation_service as automation_service

    command = shlex.join([sys.executable, '-c',
                          'import sys; sys.stderr.write("TLS profile failed\\n"); sys.exit(23)'])
    monkeypatch.setattr(automation_service, 'get_executable_path', lambda: command)
    monkeypatch.setattr(automation_service, 'get_runtime_root', lambda: str(tmp_path))
    real_run = subprocess.run

    def fake_run(args, **kwargs):
        assert args[:2] == ['osascript', '-e']
        match = re.fullmatch(r'do shell script "(.*)" with administrator privileges', args[2])
        assert match
        shell_script = match.group(1).replace(chr(92) + '"', '"').replace(chr(92) * 2, chr(92))
        return real_run(['/bin/sh', '-c', shell_script], capture_output=True, text=True, timeout=8)

    monkeypatch.setattr(automation_service.subprocess, 'run', fake_run)
    code, message = _service().sudo_self(detached=False)
    assert code == 0
    assert 'TLS profile failed' in message
    assert 'RCH_ELEVATED_CLIENT_PID=' not in message
