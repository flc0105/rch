"""Exercise elevation modes, streaming and PID reporting without elevating Linux."""

import os
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.commands.shell.standalone import run_elevated
from client.commands.shell.standalone import _elevated_mac as mac
from client.runtime.execution.context import CommandCancelledError


@pytest.mark.parametrize('platform', ['mac', 'win'])
def test_modes_dispatch_without_interpreting_direct_arguments(monkeypatch, platform):
    owner = SimpleNamespace(command_platform=platform, _checkpoint=lambda: None)
    adapter_type = run_elevated._ADAPTERS[platform]
    shell = Mock(return_value=(1, 'ok'))
    collect = Mock(return_value=(1, 'collected'))
    detached = Mock(return_value=(1, 'started'))
    opened = Mock(return_value=(1, 'opened'))
    console = Mock(return_value=(1, 'console'))
    monkeypatch.setattr(adapter_type, 'shell', shell)
    monkeypatch.setattr(adapter_type, 'collect', collect)
    monkeypatch.setattr(adapter_type, 'detached', detached)
    if platform == 'win':
        monkeypatch.setattr(adapter_type, 'open', opened)
        monkeypatch.setattr(adapter_type, 'show_console', console)

    command = 'echo "quoted value" | text'
    assert run_elevated.run_elevated(owner, '--no-confirm ' + command) == (1, 'ok')
    assert run_elevated.run_elevated(owner, '--no-confirm --shell ' + command) == (1, 'ok')
    assert [call.args for call in shell.call_args_list] == [(command,), (command,)]
    assert run_elevated.run_elevated(owner, '--no-confirm --collect -- ' + command + ' --no-confirm') == (
        1, 'collected',
    )
    collect.assert_called_once_with(command + ' --no-confirm')

    program = r'C:\Program Files\Client.exe' if platform == 'win' else '/tmp/Client binary'
    assert run_elevated.run_elevated(owner, f'--no-confirm --detached -- "{program}" "x y" |') == (1, 'started')
    detached.assert_called_once_with([program, 'x y', '|'])

    open_result = run_elevated.run_elevated(owner, f'--no-confirm --open "{program}"')
    console_result = run_elevated.run_elevated(owner, '--no-confirm --show-console ' + command)
    if platform == 'win':
        assert open_result == (1, 'opened')
        assert console_result == (1, 'console')
        opened.assert_called_once_with([program])
        console.assert_called_once_with(command)
    else:
        for status, message in (open_result, console_result):
            assert status == 0 and 'only available on Windows' in message

    for arguments in ('--shell --open echo', '--collect --detached echo', '--collect', '--shell --'):
        assert run_elevated.run_elevated(owner, '--no-confirm ' + arguments)[0] == 0
    assert run_elevated.run_elevated(owner, '--no-confirm --native echo')[0] == 0


@pytest.mark.parametrize(('code', 'expected'), [(0, (1, 'first\nlast')), (1, (0, 'shell error'))])
def test_macos_collect_runs_osascript_and_returns_one_result(monkeypatch, code, expected):
    execute = Mock(return_value=SimpleNamespace(returncode=code, stdout='first\nlast', stderr='shell error'))
    monkeypatch.setattr(mac.subprocess, 'run', execute)
    owner = SimpleNamespace(command_platform='mac', _checkpoint=lambda: None, emit_chunk=Mock())

    assert run_elevated.run_elevated(owner, '--no-confirm --collect -- echo "quoted" | cat') == expected
    execute.assert_called_once_with(
        ['osascript', '-e', r'do shell script "echo \"quoted\" | cat" with administrator privileges'],
        capture_output=True, text=True, timeout=30,
    )
    owner.emit_chunk.assert_not_called()


@pytest.fixture
def mac_helper(monkeypatch):
    if os.name != 'posix' or not shutil.which('perl'):
        pytest.skip('requires POSIX and Perl')
    popen = subprocess.Popen
    # Execute the exact script sent to osascript, leaving authorization to the
    # native integration test. The worker, shell and TCP channel are real.
    def fake_popen(args, **kwargs):
        match = re.fullmatch(r'do shell script "(.*)" with administrator privileges', args[2])
        source = match.group(1).replace(r'\"', '"').replace(chr(92) * 2, chr(92))
        return popen(['/bin/sh', '-c', source], **kwargs)

    monkeypatch.setattr(mac.subprocess, 'Popen', fake_popen)
    return SimpleNamespace(_checkpoint=lambda: None, emit_chunk=Mock())


def test_macos_shell_streams_then_reports_real_exit(mac_helper):
    seen = []
    mac_helper.emit_chunk.side_effect = lambda output: seen.append((time.monotonic(), output))
    command = "printf '中文\\n'; sleep 0.4; printf 'stderr\\n' >&2; exit 7"
    result = mac.MacElevation(mac_helper).shell(command)
    assert result == (0, 'Elevated command exited with code 7')
    assert [chunk for _, chunk in seen] == ['中文', 'stderr']
    assert seen[-1][0] - seen[0][0] >= 0.2


def test_macos_detached_returns_real_pid_and_accepts_fast_exit(mac_helper, tmp_path):
    output = tmp_path / 'pid and session.txt'
    argv = [sys.executable, '-c',
            'from pathlib import Path; import os,sys; Path(sys.argv[1]).write_text(f"{os.getpid()} {os.getsid(0)}")',
            str(output)]
    result, message = mac.MacElevation(mac_helper).detached(argv)
    assert result == 1
    pid = re.search(r'PID: (\d+)', message).group(1)
    deadline = time.monotonic() + 2
    while (not output.exists() or not output.stat().st_size) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert output.read_text() == f'{pid} {pid}'
    with pytest.raises(OSError, match='Cannot start'):
        mac.MacElevation(mac_helper).detached([str(tmp_path / 'missing')])


def test_macos_cancelled_shell_exits_before_delayed_side_effect(mac_helper, tmp_path):
    output = tmp_path / 'cancelled'
    command = f"printf 'started\\n'; sleep 0.5; touch '{output}'"
    def checkpoint():
        if mac_helper.emit_chunk.called:
            raise CommandCancelledError('cancelled')

    mac_helper._checkpoint = checkpoint
    with pytest.raises(CommandCancelledError):
        mac.MacElevation(mac_helper).shell(command)
    time.sleep(0.6)
    assert not output.exists()
