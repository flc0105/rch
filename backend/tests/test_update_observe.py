"""Observed Update keeps the originating Reverse Client alive for diagnosis."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.commands.shell.standalone import update as command
from core.protocol.references import session_action_reference
from server.application.preferences.notification_event_projector import NotificationEventProjector


def _prepare_update(monkeypatch, tmp_path, *, mode='reverse', managed=False, fail=False):
    script = tmp_path / 'bundle' / 'rchclient.py'
    script.parent.mkdir()
    script.write_text('print("candidate output")')
    log_path = tmp_path / 'update-test.log'
    log_path.write_text('')
    state = {'spawn': [], 'exit': [], 'events': []}
    monkeypatch.setitem(command.RUNTIME_CONFIG, 'connection_mode', mode)
    monkeypatch.setattr(command, '_get_update_owner', lambda: ('mac', {
        'source': 'launchagent' if managed else 'terminal',
    }))
    monkeypatch.setattr(command.UpdatePreparation, 'run', lambda _: str(script))
    monkeypatch.setattr(command, '_expected_revision', lambda _: 'rev-abc')
    monkeypatch.setattr(command, 'make_client_startup_log', lambda **kw: str(log_path))
    process = SimpleNamespace(pid=7218, poll=lambda: None,
                              terminate=lambda: state.setdefault('terminated', True),
                              wait=lambda **kw: 0)
    def spawn(*args, **kwargs):
        state['spawn'].append((args, kwargs))
        return process
    monkeypatch.setattr(command, 'spawn_detached_python_script', spawn)
    def signal_accept(**kwargs):
        if fail:
            raise TimeoutError('Updated Client did not register')
        return {'client_id': 'new-client-id'}
    signal = SimpleNamespace(port=12345, secret='token', accept=signal_accept)
    class SignalContext:
        def __enter__(self): return signal
        def __exit__(self, *args): return None
    monkeypatch.setattr(command, 'SignalListener', SignalContext)
    monkeypatch.setattr(command, '_schedule_exit_after_update', lambda *_: state['exit'].append('scheduled'))
    client = SimpleNamespace(emit_completed=lambda **kw: state['events'].append(kw),
                             socket=SimpleNamespace(), execution_context=object(),
                             _checkpoint=lambda: None)
    return client, state, log_path


def test_observe_success_keeps_old_and_references_startup_log(monkeypatch, tmp_path):
    client, state, log = _prepare_update(monkeypatch, tmp_path)
    command.update(client, '--observe')
    assert state['exit'] == []
    assert len(state['spawn']) == 1
    assert state['spawn'][0][1]['output_path'] == str(log)
    result, = state['events']
    assert result['status'] == 'success'
    assert 'Verify the new Client' in result['message']
    assert result['references'] == [
        {'type': 'log_file', 'path': str(log), 'title': 'Client update'},
        {'type': 'session_action', 'action': 'kill_instance'},
    ]
    projector = NotificationEventProjector(history_store=None, server=None)
    notification = projector._build_command_result({'client_id': 'old-client-id', 'result': {
        'event_type': 'completed', 'status': 'success', 'message': result['message'],
        'references': result['references'],
    }})
    assert notification['title'] == 'Client Instance Started'
    assert notification['context']['client_id'] == 'old-client-id'
    assert notification['context']['log_path'] == str(log)
    assert notification['actions'][0]['type'] == 'view_client_log'



def test_observe_success_notifies_over_existing_web_sse_bus(monkeypatch, tmp_path):
    from server.web.event_bus import WebEventBus

    client, state, log = _prepare_update(monkeypatch, tmp_path)
    command.update(client, '--observe')
    result, = state['events']
    stored = []

    class Store:
        def add_notification(self, notification):
            stored.append(notification)
            return notification, True

    bus = WebEventBus()
    bus.set_notification_recorder(
        NotificationEventProjector(history_store=Store(), server=None).record_event)
    receiver = bus.subscribe(tab_id='update-tab')
    bus.publish('command_result_batch', {
        'client_id': 'old-client-id', 'command_id': 17,
        'results': [{'result': {'event_type': 'completed', **result}}],
    }, target_tab_id='update-tab')
    events = [receiver.get_nowait(), receiver.get_nowait()]
    assert [item['event'] for item in events] == [
        'command_result_batch', 'notification_center_updated',
    ]
    assert len(stored) == 1
    notification = events[1]['data']['notification']
    assert notification['title'] == 'Client Instance Started'
    assert notification['context']['client_id'] == 'old-client-id'
    assert notification['context']['log_path'] == str(log)
    assert notification['actions'][0]['type'] == 'view_client_log'


def test_observe_failure_carries_log_while_original_survives(monkeypatch, tmp_path):
    client, state, log = _prepare_update(monkeypatch, tmp_path, fail=True)
    command.update(client, '--observe')
    assert state['exit'] == []
    assert state.get('terminated') is True
    result, = state['events']
    assert result['status'] == 'error'
    assert 'Original Client remains online' in result['message']
    assert result['references'][0] == {'type': 'log_file', 'path': str(log), 'title': 'Client update'}
    assert result['references'][1] == session_action_reference('kill_instance')


def test_default_update_still_schedules_exit_without_new_log(monkeypatch, tmp_path):
    client, state, _ = _prepare_update(monkeypatch, tmp_path)
    command.update(client)
    assert state['exit'] == ['scheduled']
    assert state['events'][0]['status'] == 'success'
    assert 'references' not in state['events'][0]
    assert 'output_path' not in state['spawn'][0][1]


@pytest.mark.parametrize('mode,managed', [('bind', False), ('reverse', True)])
def test_observe_rejected_before_preparation(monkeypatch, tmp_path, mode, managed):
    client, state, _ = _prepare_update(monkeypatch, tmp_path, mode=mode, managed=managed)
    command.update(client, '--observe')
    assert state['spawn'] == []
    assert state['events'][0]['status'] == 'error'
    assert '--observe only supports' in state['events'][0]['message']


def test_session_action_reference_is_strict():
    with pytest.raises(ValueError, match='Unsupported'):
        session_action_reference('relaunch_instance')


def test_candidate_stdout_and_startup_traceback_survive_failed_process(tmp_path):
    """Real subprocess evidence remains readable after a candidate exits offline."""
    from client.runtime.client_util import spawn_detached_python_script

    script = tmp_path / 'candidate.py'
    script.write_text(
        'import sys\n'
        'print("candidate startup", flush=True)\n'
        'print("ModuleNotFoundError: missing_dependency", file=sys.stderr, flush=True)\n'
        'sys.exit(1)\n',
        encoding='utf-8',
    )
    log_path = tmp_path / 'candidate.log'
    process = spawn_detached_python_script(str(script), output_path=str(log_path))
    assert process.wait(timeout=5) == 1
    log = log_path.read_text(encoding='utf-8')
    assert 'candidate startup' in log
    assert 'ModuleNotFoundError: missing_dependency' in log
