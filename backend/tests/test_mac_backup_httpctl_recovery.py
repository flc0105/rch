"""Regression: Homebrew inventory must not stall a backup; HTTP recovery bypasses busy."""
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.application.tasks.task_service import WebTaskService
from server.application.connection.control_command_store import ControlCommandStore

ROOT = Path(__file__).parents[1]
BREW_FILE = ROOT / 'server/resources/scripts/macos/recon/brew_packages.py'


def load_brew():
    spec = importlib.util.spec_from_file_location('test_brew_inventory', BREW_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_homebrew_rich_inventory_timeout_falls_back_preserving_schema(monkeypatch, capsys):
    brew = load_brew()
    log = []
    monkeypatch.setattr(brew, '_brew_executable', lambda: '/usr/bin/brew')
    monkeypatch.setattr(brew.context, 'progress', lambda message: log.append(message))

    def fake_run(executable, args, timeout):
        assert timeout <= 20
        if args[0] == 'info':
            raise subprocess.TimeoutExpired(args, timeout)
        return 'git 2.46\n' if '--formula' in args else 'firefox 134\n'

    monkeypatch.setattr(brew, '_brew_command', fake_run)
    brew.main()
    captured = capsys.readouterr()
    rows = json.loads(captured.out)
    assert [(x['type'], x['token']) for x in rows] == [('cask', 'firefox'), ('formula', 'git')]
    assert all(set(x) == {'type', 'token', 'name', 'tap', 'installed_ver', 'desc',
                          'homepage', 'url', 'depends_on', 'installed_time'} for x in rows)
    assert 'fallback' in captured.err
    assert any('Fallback' in item for item in log)


def test_homebrew_fast_success_keeps_rich_fields(monkeypatch, capsys):
    brew = load_brew()
    monkeypatch.setattr(brew, '_brew_executable', lambda: 'brew')
    monkeypatch.setattr(brew.context, 'progress', lambda _text: None)
    data = {'formulae': [{'name': 'git', 'desc': 'version control', 'installed': [{'version': '2.46'}]}], 'casks': []}
    monkeypatch.setattr(brew, '_brew_command', lambda *_args, **_kwargs: json.dumps(data))
    brew.main()
    record = json.loads(capsys.readouterr().out)[0]
    assert record['desc'] == 'version control'
    assert record['installed_ver'] == '2.46'


def test_homebrew_failure_is_bounded_and_reported(monkeypatch, capsys):
    brew = load_brew()
    monkeypatch.setattr(brew, '_brew_executable', lambda: 'brew')
    monkeypatch.setattr(brew.context, 'progress', lambda _text: None)
    monkeypatch.setattr(brew, '_brew_command', lambda exe, args, timeout: (_ for _ in ()).throw(subprocess.TimeoutExpired(args, timeout)))
    with pytest.raises(SystemExit) as err:
        brew.main()
    assert err.value.code == 1
    assert json.loads(capsys.readouterr().out)['error']


def test_brew_env_disables_auto_update(monkeypatch):
    brew = load_brew()
    calls = []
    def fake_run(args, **opts):
        calls.append((args, opts))
        return SimpleNamespace(returncode=0, stdout='done', stderr='')
    monkeypatch.setattr(brew.subprocess, 'run', fake_run)
    assert brew._brew_command('brew', ('info', '--json=v2', '--installed'), 20) == 'done'
    assert calls[0][1]['timeout'] == 20
    assert calls[0][1]['env']['HOMEBREW_NO_AUTO_UPDATE'] == '1'


def test_httpctl_only_bypasses_foreground_busy_guard(monkeypatch):
    session = Mock()
    session.session_info = SimpleNamespace(client_id='c-1')
    session.acquire_foreground_task.side_effect = RuntimeError('Client is busy: run_script')
    history = Mock()
    history.begin_execution.return_value = 'history-1'
    server = Mock(command_history_orchestrator=history)
    server.get_target_connection_by_client_id.return_value = session
    tasks = Mock()
    tasks.create_task.return_value = {'task_id': 'http-task-1', 'tab_id': 'tab-1', 'client_id': 'c-1'}
    service = WebTaskService(server, tasks, Mock(), Mock(run_command_task=lambda _: None))
    launched = []
    monkeypatch.setattr(service, '_start_task_thread', lambda runner, ctx: launched.append((runner, ctx)))

    for action in ('kill', 'relaunch', 'clone'):
        result = service.submit_web_command('c-1', f'httpctl {action}')
        assert result['task_id'] == 'http-task-1'
    assert len(launched) == 3
    # Exact builtin name plus shell-compatible action parsing; uppercase
    # command names must never bypass guard and reach a remote shell.
    assert service._is_http_control_command('httpctl "RELAUNCH"')
    assert not service._is_http_control_command('HTTPCTL relaunch')
    assert not service._is_http_control_command('httpctl relaunch ; whoami')
    assert not service._is_http_control_command('httpctl "broken')
    session.acquire_foreground_task.assert_not_called()

    with pytest.raises(RuntimeError, match='Client is busy'):
        service.submit_web_command('c-1', 'pwd')
    with pytest.raises(RuntimeError, match='Client is busy'):
        service.submit_web_command('c-1', 'httpctl invalid')
    assert len(launched) == 3


def test_control_queue_can_be_written_while_client_is_offline():
    flask = pytest.importorskip('flask')
    from server.web.routes.stream_control import create_stream_control_blueprint
    app = flask.Flask(__name__)
    server = Mock()
    # Offline target resolution must never be necessary for watchdog control.
    server.get_target_connection_by_client_id.side_effect = RuntimeError('Client is offline')
    server.web_service = Mock()
    app.register_blueprint(create_stream_control_blueprint(server))
    with app.test_client() as client:
        response = client.post('/api/connections/offline-1/control', json={'command': 'relaunch'})
        assert response.status_code == 200
        assert response.get_json()['data']['command'] == 'relaunch'
        assert client.post('/api/connections/offline-1/control', json={'command': 'notallowed'}).status_code == 400
    server.get_target_connection_by_client_id.assert_not_called()
    from server.application.connection.control_command_store import get_control_command_store
    assert get_control_command_store().pop_pending_command('offline-1')['command'] == 'relaunch'
