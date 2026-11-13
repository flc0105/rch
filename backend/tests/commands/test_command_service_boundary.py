"""Command services work without traversing Web API facades."""
import json
from types import SimpleNamespace

import pytest

from core.protocol.job_control import build_job_control_result
from server.application.artifact.artifact_events import publish_artifact_created
from server.application.command.command_builtin_services import CommandBuiltinServices
from server.application.command.job_builtin_support import JobBuiltinSupport
from server.application.jobs.background_job_service import BackgroundJobService
from server.application.web.job_api import WebJobApi


class Catalog:
    def list_background_job_catalog(self):
        return [{'job_name': 'demo', 'metadata': {'execution_mode': 'inproc'}}]

    def get_job_metadata(self, name):
        assert name == 'demo'
        return {'execution_mode': 'subprocess', 'allowed': ['subprocess']}


class JobStore:
    def list_jobs(self, client_id):
        return []


class EventBus:
    def __init__(self):
        self.events = []

    def publish(self, name, payload):
        self.events.append((name, payload))


def make_job_service():
    catalog = Catalog()
    service = BackgroundJobService(EventBus(), JobStore(), None, catalog)
    service.has_active_job = lambda client_id, job_name: False
    return service, catalog


def test_shared_job_start_policy_in_web_and_command():
    service, catalog = make_job_service()
    api = WebJobApi(service, catalog)
    assert api.list_background_job_catalog('client1') == catalog.list_background_job_catalog()
    assert api.prepare_background_job_start('client1', 'demo') == 'subprocess'
    assert service.prepare_job_start('client1', 'demo') == 'subprocess'
    with pytest.raises(ValueError, match='not supported'):
        service.prepare_job_start('client1', 'demo', 'inproc')
    with pytest.raises(ValueError, match='job_name is required'):
        api.prepare_background_job_start('client1', '')
    service.has_active_job = lambda client_id, job_name: True
    with pytest.raises(ValueError, match='already running'):
        api.prepare_background_job_start('client1', 'demo')


def test_job_control_command_is_identical_and_download_is_client_owned():
    service, catalog = make_job_service()
    commands = []

    class Remote:
        def stream_command(self, conn, command, **kwargs):
            commands.append((kwargs["payload"], kwargs))
            yield (1, build_job_control_result('start', 'started', data={}))

    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='client1'))
    support = JobBuiltinSupport(SimpleNamespace(), conn, Remote(), service, catalog)
    # The Server only sends typed Control; Client download/exec remains separate.
    events = list(support._send('start', job_name='demo', execution_mode='subprocess'))
    assert commands[0][0] == {'job_name': 'demo', 'execution_mode': 'subprocess'}
    assert commands[0][1]['command_type'] == 'control'
    assert events and events[-1][0] == 1


def test_artifact_created_payload_keeps_web_notification_shape():
    bus = EventBus()
    publish_artifact_created(bus, {'artifact_id': 'a', 'scope': 'saved', 'category': 'command_output', 'source_command_id': 13})
    assert bus.events == [('artifact_created', {
        'artifact_id': 'a', 'artifact_type': '', 'category': 'command_output',
        'hostname': '', 'machine_id': '', 'client_id': '', 'source_command_id': 13,
        'original_name': '', 'stored_name': '', 'size': 0, 'saved_at': '',
        'download_url': '', 'preview_url': '',
    })]
    publish_artifact_created(bus, 'invalid')
    assert len(bus.events) == 1


def test_dependencies_are_immutable_and_explicit():
    services = CommandBuiltinServices(*range(11))
    assert services.background_job_service == 0
    assert services.task_store == 10
    with pytest.raises((AttributeError, TypeError)):
        services.background_job_service = 'changed'


def test_saveout_keeps_artifact_created_and_history_binding(tmp_path):
    from server.application.command.command_output_builtin_support import CommandOutputBuiltinSupport
    from server.application.history.lifecycle_adapter import LifecycleAdapter

    bus = EventBus()
    file_path = tmp_path / 'output.txt'
    attached = []

    class Artifacts:
        def allocate_command_output_artifact_path(self, **kwargs):
            return {'file_path': str(file_path), 'machine_id': 'machine1', 'original_name': 'output.txt'}

        def register_command_output_artifact(self, *, allocation, output_kind, hostname, machine_id,
                                             client_id='', addr='', source_command='', source_command_id=None,
                                             extra=None):
            assert source_command_id == 'cmd1'
            return {'artifact_id': 'a1', 'category': 'command_output', 'original_name': 'output.txt', 'size': 6}

    conn = SimpleNamespace(
        session_info=SimpleNamespace(machine_id='machine1', hostname='host', client_id='c1'),
        get_foreground_task=lambda: {'command_id': 'cmd1'},
    )
    # The lifecycle adapter owns Activity attachment, not the saveout builtin.
    coordinator = SimpleNamespace(bind_uploaded_artifact=lambda current, command_id, artifact:
                                  attached.append((current, 'h1' if command_id == 'cmd1' else '', artifact)))
    adapter = LifecycleAdapter(coordinator)
    artifact_service = adapter.instrument_artifacts(Artifacts(), lambda client_id: conn if client_id == 'c1' else None)
    support = CommandOutputBuiltinSupport(SimpleNamespace(), conn, None, None, lambda: 'h1', artifact_service, bus)
    support._build_inner_executor = lambda command: lambda: [(1, 'hello')]
    result = list(support.saveout('echo hello'))
    assert result and result[-1][0] == 1
    assert file_path.read_text() == 'hello\n'
    assert attached and attached[0][0] is conn and attached[0][1] == 'h1' and attached[0][2]['artifact_id'] == 'a1'
    assert len(bus.events) == 1 and bus.events[0][1]['artifact_id'] == 'a1'


def test_notify_publishes_through_device_event_service_without_web():
    from server.application.command.command_notify_builtin_support import CommandNotifyBuiltinSupport

    received = []
    service = SimpleNamespace(ingest=lambda payload: received.append(payload))
    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='c1', hostname='host'))
    support = CommandNotifyBuiltinSupport(conn, None, lambda: 'history1', service)
    support._build_inner_executor = lambda command: lambda: [(0, 'temporary warning'), (1, 'done')]
    assert list(support.notify('echo hello')) == [(0, 'temporary warning'), (1, 'done')]
    assert len(received) == 1
    assert received[0]['kind'] == 'command.notify.finished'
    assert received[0]['data']['status'] == 'success'
    assert received[0]['data']['history_entry_id'] == 'history1'
