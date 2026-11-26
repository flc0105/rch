"""Revision-on-request and detachable Client startup log contracts."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from client.commands.runtime.manifest_metadata import command_metadata
from client.commands.shell.decorators import shell_command
from client.commands.shell.common import session as session_commands
from client.connection import handshake
from client.session.control import SessionControl
from core.protocol.control import SessionAction
from core.protocol.message_queue import ResultChunk
from server.application.connection.connection_service import WebConnectionService
from server.application.preferences.notification_event_projector import NotificationEventProjector


def test_revision_details_detect_source_changed_after_process_started(monkeypatch, tmp_path):
    from core import client_revision

    source = tmp_path / 'client' / 'module.py'
    source.parent.mkdir()
    source.write_text('VALUE = "old"\n', encoding='utf-8')
    monkeypatch.setattr(client_revision, '_get_default_source_root', lambda: str(tmp_path))
    monkeypatch.setattr(handshake, '_CLIENT_REVISION_MANIFEST', None)
    monkeypatch.setattr(handshake, '_CLIENT_REVISION_FILE_STATS', None)
    old_revision = handshake._get_client_revision_manifest()['revision']
    assert handshake.get_revision_file_stats_at_start()['client/module.py']

    source.write_text('VALUE = "new"\n', encoding='utf-8')
    new_revision = client_revision.build_client_revision_manifest(include_files=False)['revision']
    assert old_revision != new_revision

    client_control = SessionControl(SimpleNamespace())
    status, detail = client_control.execute(None, SessionAction.GET_REVISION_FILES, {})
    assert status == 1
    assert detail['changed_since_start'] == [{'path': 'client/module.py', 'change': 'modified'}]
    assert detail['files']['client/module.py'] == (
        client_revision.build_client_revision_manifest(include_files=True)['files']['client/module.py'])

    class FakeSession:
        session_info = SimpleNamespace(client_revision=old_revision)
        def send_command(self, *args, **kwargs):
            event = {'event_type': 'completed', 'status': 'success', 'data': detail}
            yield ResultChunk(1, event, True, event=event)
    service = WebConnectionService(
        SimpleNamespace(get_target_connection_by_client_id=lambda _id: FakeSession()), None, None)
    monkeypatch.setattr(service, '_build_connection_state', lambda _session: 'online')
    result = service.get_client_revision_status('client-1')
    assert result['state'] == 'outdated'
    assert result['changed_files_available'] is True
    assert result['changed_files'] == [{'path': 'client/module.py', 'change': 'modified'}]


def test_command_manifest_is_flat_without_execution_only_policies():
    @shell_command('Interactive command', group='test', may_interact=True, output='stream')
    def handler():
        return 1, 'ok'
    handler.command_timeout = 12
    fields = command_metadata(handler)
    assert handler.command_may_interact is True
    assert fields['cancel_policy'] == 'none'
    for excluded in ('timeout', 'output', 'interaction', 'may_interact', 'source', 'suggest'):
        assert excluded not in fields
    # Runtime properties still control execution behavior.
    assert handler.command_output == 'stream'
    assert handler.command_timeout == 12


def test_spawn_instance_writes_to_random_log_without_pipe(monkeypatch, tmp_path):
    from client.runtime import temp_workspace
    monkeypatch.setattr(temp_workspace, 'get_temp_category_dir', lambda *_a, **_k: str(tmp_path))
    monkeypatch.setattr(session_commands, 'get_executable_argv', lambda: [
        sys.executable, '-c',
        'import sys; print("hello from stdout", flush=True); '
        'print("hello from stderr", file=sys.stderr, flush=True)',
    ])
    monkeypatch.setattr(session_commands, 'get_runtime_root', lambda: str(tmp_path))
    command = SimpleNamespace()
    # Call the underlying business function directly through its real decorators.
    from client.config import config
    previous = config.RUNTIME_CONFIG.get('connection_mode')
    try:
        config.RUNTIME_CONFIG['connection_mode'] = 'reverse'
        status, payload = session_commands.spawn_instance(command)
    finally:
        config.RUNTIME_CONFIG['connection_mode'] = previous
    assert status == 1
    assert payload['event_type'] == 'completed'
    assert payload['references'][0]['type'] == 'log_file'
    path = Path(payload['references'][0]['path'])
    assert path.parent == tmp_path and path.name.startswith('spawn-')
    pid = payload['data']['pid']
    assert pid > 0
    import time
    for _ in range(50):
        if 'hello from stdout' in path.read_text(encoding='utf-8'):
            break
        time.sleep(.04)
    content = path.read_text(encoding='utf-8')
    assert 'hello from stdout' in content
    assert 'hello from stderr' in content


def test_successful_log_reference_becomes_notification_action():
    projector = NotificationEventProjector(history_store=None, server=None)
    payload = {
        'client_id': 'client-01', 'command_id': 'cmd-02',
        'result': {'event_type': 'completed', 'status': 'success',
                   'message': 'New client instance started',
                   'references': [{'type': 'log_file', 'path': '/tmp/client-start-xyz.log',
                                   'title': 'Client startup'}]},
    }
    record = projector._build_command_result(payload)
    assert record['title'] == 'Client Instance Started'
    assert record['notification_key'] == 'device_event'
    assert record['actions'][0]['type'] == 'view_client_log'
    assert record['context']['log_path'] == '/tmp/client-start-xyz.log'
    batch = projector._build_command_result_batch({
        'client_id': 'client-01', 'command_id': 'cmd-02',
        'results': [{'result': {'event_type': 'progress', 'message': 'starting'}},
                    {'result': payload['result']}],
    })
    assert batch['context']['log_path'] == '/tmp/client-start-xyz.log'
    assert projector._build_command_result({**payload, 'result': {'event_type': 'chunk'}}) is None
    # Existing Device Event projection continues using its original argument contract.
    assert projector._build_device_event({'client_id': 'client-01', 'kind': 'custom.event'})['title'] == 'Device Event'


def test_batched_launch_result_creates_notification_on_existing_web_event_bus():
    from server.web.event_bus import WebEventBus

    stored = []
    class Store:
        def add_notification(self, notification):
            stored.append(notification)
            return notification, True

    bus = WebEventBus()
    bus.set_notification_recorder(NotificationEventProjector(history_store=Store(), server=None).record_event)
    receiver = bus.subscribe(tab_id='terminal-1')
    bus.publish('command_result_batch', {
        'client_id': 'client-01', 'command_id': 17,
        'results': [{'text': 'Starting'}, {'result': {
            'event_type': 'completed', 'status': 'success', 'message': 'Started',
            'references': [{'type': 'log_file', 'path': '/tmp/start.log', 'title': 'Client startup'}],
        }}],
    }, target_tab_id='terminal-1')
    events = [receiver.get_nowait(), receiver.get_nowait()]
    assert [event['event'] for event in events] == ['command_result_batch', 'notification_center_updated']
    assert len(stored) == 1
    assert stored[0]['actions'][0]['type'] == 'view_client_log'
