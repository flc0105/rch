"""External Tool Control protocol and terminal outcome regression checks."""
from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from client.external_tools import control as external_control
from core.external_tools.payload import client_install_payload
from core.protocol.control import (
    ControlDomain, ExternalToolAction as A, ActivityPolicy, ExecutionPolicy,
    action_spec, build_control_message, control_actions,
)


@pytest.fixture
def adapter(monkeypatch):
    service_calls = []

    class FakeService:
        def __init__(self, scope):
            self.scope = scope

        def install_statuses_payload(self, payload):
            service_calls.append((A.GET_INSTALL_STATUSES, payload))
            return {'items': [
                {'package_id': p.get('package_id'), 'installed': p.get('package_id') != 'broken',
                 **({'error': 'unreadable metadata'} if p.get('package_id') == 'broken' else {})}
                for p in payload['tools']
            ]}

        def list_instances_all_payload(self, payload):
            service_calls.append((A.LIST_INSTANCES, payload))
            items = [{'tool_id': 'frp.frps', 'package_id': 'frp', 'module_id': 'frps',
                      'instance_id': 'worker1', 'status': 'running', 'running': True, 'pid': 1234},
                     {'tool_id': 'frp.frps', 'package_id': 'frp', 'module_id': 'frps',
                      'instance_id': 'worker2', 'status': 'stopped', 'running': False, 'pid': None}]
            return {'items': items, 'by_tool': {'frp.frps': items}}

        def oneshot_payload(self, payload):
            return {'success': False, 'timed_out': True, 'returncode': None,
                    'message': 'FFmpeg version probe timed out',
                    'stdout': 'before timeout', 'stderr': 'command expired',
                    'platform': 'win', 'arch': 'amd64', 'install': {'path': '/do/not/return'}}

        def install_payload(self, payload):
            return {'installed': True, 'message': 'Package installed successfully',
                    'install_dir': '/do/not/return', 'already_installed': False,
                    'executable_path': '/do/not/return/exec', 'used_cache': True}

        def uninstall_payload(self, payload):
            return {'installed': False, 'message': 'Package uninstalled',
                    'install_dir': '/do/not/return', 'removed': True}

        def clear_cache_payload(self, payload):
            return {'message': 'Package cache cleared', 'cache_removed': True, 'cache': {'path': '/do/not/return'}}

        def expand_path(self, path):
            return path

        def start_payload(self, payload):
            return {'running': False, 'message': 'Process exited before becoming ready'}

        def _instance_definition_path(self, payload):
            return '/tmp/rch-control-test/worker1/instance.json'

    monkeypatch.setattr(external_control, 'ExternalToolClientService', FakeService)
    runtime = SimpleNamespace(command_variable_resolver=SimpleNamespace(resolve=lambda s: s))
    return external_control.ExternalToolControl(runtime), service_calls


def test_external_control_has_exactly_17_declared_actions_with_policies():
    actions = dict(control_actions(ControlDomain.EXTERNAL_TOOL))
    assert set(actions) == set(A)
    assert len(actions) == 17
    for action in A:
        spec = action_spec(ControlDomain.EXTERNAL_TOOL, action)
        assert spec.policy in (ExecutionPolicy.FOREGROUND, ExecutionPolicy.INDEPENDENT)
        assert spec.activity in (ActivityPolicy.ALWAYS, ActivityPolicy.OPTIONAL)
    assert action_spec(ControlDomain.EXTERNAL_TOOL, A.GET_INSTALL_STATUSES).activity == ActivityPolicy.OPTIONAL
    assert actions[A.STOP_INSTANCE] == ExecutionPolicy.INDEPENDENT
    assert actions[A.RESTART_INSTANCE] == ExecutionPolicy.FOREGROUND


def test_wire_action_is_single_canonical_field_and_real_meta_payload_has_no_duplicate_action():
    meta_path = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas/ffmpeg.json'
    ffmpeg = json.loads(meta_path.read_text(encoding='utf-8'))
    payload = client_install_payload(
        ffmpeg, {'platform': 'win', 'arch': 'amd64', 'package_key': 'win-amd64',
                 'install_dir': '/managed/ffmpeg'},
        source='', filename=ffmpeg['platform_packages']['win-amd64']['filename'],
        download_url='/api/external-tools/packages/ffmpeg.zip',
        executable_rel_path='bin/ffmpeg.exe', skip_if_exists='/managed/ffmpeg',
    )
    assert payload['package_id'] == 'ffmpeg'
    assert 'action' not in payload
    packet = build_control_message(41, ControlDomain.EXTERNAL_TOOL, A.GET_INSTALL_STATUSES,
                                   {'tools': [payload]})
    assert packet['action'] == 'get_install_statuses'
    assert 'action' not in packet['payload']['tools'][0]
    assert 'text' not in packet


def test_single_and_bulk_install_status_share_action_with_true_terminal_status(adapter):
    executor, calls = adapter
    code, success = executor.execute(object(), A.GET_INSTALL_STATUSES, {'tools': [{'package_id': 'ffmpeg'}]})
    assert code == 1 and success['status'] == 'success'
    assert success['event_type'] == 'completed'
    assert len(success['data']['items']) == 1
    code, partial = executor.execute(object(), A.GET_INSTALL_STATUSES, {'tools': [
        {'package_id': 'ffmpeg'}, {'package_id': 'broken'}]})
    assert code == 1 and partial['status'] == 'partial'
    assert partial['data']['items'][1]['error'] == 'unreadable metadata'
    code, failure = executor.execute(object(), A.GET_INSTALL_STATUSES, {'tools': [{'package_id': 'broken'}]})
    assert code == 0 and failure['status'] == 'error'
    assert all(action == A.GET_INSTALL_STATUSES for action, _ in calls)


def test_instance_single_filter_uses_plural_action_without_other_instance_data(adapter):
    executor, calls = adapter
    code, result = executor.execute(object(), A.LIST_INSTANCES, {'tools': [
        {'tool_id': 'frp.frps', 'package_id': 'frp', 'module_id': 'frps',
         'instance_ids': ['worker1']} ]})
    assert code == 1 and result['status'] == 'success'
    assert [item['instance_id'] for item in result['data']['items']] == ['worker1']
    assert [item['instance_id'] for item in result['data']['by_tool']['frp.frps']] == ['worker1']
    code, missing = executor.execute(object(), A.LIST_INSTANCES, {'tools': [
        {'tool_id': 'frp.frps', 'package_id': 'frp', 'module_id': 'frps',
         'instance_ids': ['absent']} ]})
    assert code == 0 and missing['status'] == 'error' and 'not found' in missing['message'].lower()
    assert all(action == A.LIST_INSTANCES for action, _ in calls)


def test_oneshot_timeout_is_not_falsely_reported_as_success(adapter):
    executor, _ = adapter
    code, result = executor.execute(object(), A.RUN_ONESHOT,
                                    {'tool_id': 'ffmpeg.version', 'execution': 'oneshot'})
    assert code == 0 and result['event_type'] == 'completed'
    assert result['status'] == 'timed_out'
    assert result['data']['success'] is False
    assert result['data']['stdout'] == 'before timeout'
    assert result['data']['stderr'] == 'command expired'
    assert 'install' not in result['data'] and 'platform' not in result['data']
    assert 'message' not in result['data']  # already in the Result Envelope


def test_package_mutations_return_only_terminal_message(adapter):
    executor, _ = adapter
    for action, message in (
        (A.INSTALL_PACKAGE, 'Package installed successfully'),
        (A.UNINSTALL_PACKAGE, 'Package uninstalled'),
        (A.CLEAR_PACKAGE_CACHE, 'Package cache cleared'),
    ):
        code, event = executor.execute(object(), action, {'package_id': 'frp'})
        assert code == 1
        assert event == {'event_type': 'completed', 'status': 'success', 'message': message}


def test_server_consumes_message_only_and_preserves_oneshot_failure_output():
    from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService
    from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService

    metas = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas'
    catalog = ExternalToolCatalogService(str(metas), str(metas.parent / 'packages'))

    class FakeRemote:
        def run_foreground_control(self, client_id, domain, action, payload, **kwargs):
            if action == A.RUN_ONESHOT:
                return 0, {'event_type': 'completed', 'status': 'error',
                           'message': 'FFmpeg execution failed',
                           'data': {'success': False, 'returncode': 2, 'stdout': 'start', 'stderr': 'bad arg'}}
            return 1, {'event_type': 'completed', 'status': 'success', 'message': 'Installed successfully'}

    runtime = ExternalToolRuntimeService(catalog, command_execution_api=None,
                                         remote_execution_service=FakeRemote())
    assert runtime.remote_execution_service is runtime.core.remote_execution_service
    client = runtime.client_lifecycle_runtime
    installed = client._run_client_control('target', A.INSTALL_PACKAGE, {'package_id': 'frp'}, message_only=True)
    assert installed == {'message': 'Installed successfully'}
    details = client._run_client_control('target', A.RUN_ONESHOT, {'tool_id': 'ffmpeg.version'},
                                         return_failed_data=True)
    assert details == {'success': False, 'returncode': 2, 'stdout': 'start', 'stderr': 'bad arg'}
    import pytest
    with pytest.raises(RuntimeError, match='FFmpeg execution failed'):
        client._run_client_control('target', A.RUN_ONESHOT, {'tool_id': 'ffmpeg.version'})


def test_start_without_running_state_is_error_not_success(adapter):
    executor, _ = adapter
    code, result = executor.execute(object(), A.START_INSTANCE, {
        'package_id': 'frp', 'module_id': 'frps', 'instance_id': 'worker1',
        'runtime': {'pid_file': '/tmp/rch-control-test/worker1/tool.pid',
                    'state_file': '/tmp/rch-control-test/worker1/state.json',
                    'stdout': '/tmp/rch-control-test/worker1/stdout.log'},
    })
    assert code == 0 and result['status'] == 'error'
    assert 'Process exited' in result['message']


def test_real_frp_meta_instance_actions_have_only_consumed_request_fields():
    from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
    from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService

    metas = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas'
    catalog = ExternalToolCatalogService(str(metas), str(metas.parent / 'packages'))
    builder = ExternalToolRuntimeService(catalog, command_execution_api=None).payload_builder
    meta = catalog.get_tool('frp.frps')
    status = builder.build_client_action_payload(meta, 'status', instance_id='worker1')
    assert status == {'tool_id': 'frp.frps', 'package_id': 'frp',
                      'module_id': 'frps', 'instance_id': 'worker1'}
    logs = builder.build_client_action_payload(meta, 'logs', instance_id='worker1',
                                                max_bytes=4096, cursor='10:20:1c')
    assert logs == {**status, 'max_bytes': 4096, 'cursor': '10:20:1c'}
    stop = builder.build_client_action_payload(meta, 'stop', instance_id='worker1')
    assert set(stop) == {*status, 'lifecycle'}
    assert 'runtime' not in stop and 'params' not in stop and 'action' not in stop


def test_nested_log_snapshot_binds_and_releases_own_cancel_target():
    from server.connection.runtime.session_runtime import ClientSessionRuntime
    from server.connection.channel.session_command_channel import ClientSessionCommandChannel

    class FakeConnection:
        def __init__(self):
            self.runtime = ClientSessionRuntime()
            self.context = SimpleNamespace(activity_coordinator=None, command_dispatch_adapter=None)
            self.sent = []

        def send(self, packet):
            self.sent.append(packet)
            self.runtime.pending_results.deliver(packet['id'], {
                'type': 'result', 'id': packet['id'], 'event_type': 'completed',
                'status': 'success', 'message': 'log read',
                'data': {'content': 'hello\n', 'cursor': '1:2:3', 'running': False},
            })

    conn = FakeConnection()
    conn.runtime.acquire_foreground_task(task_type='command',
        command='xt instance logs frp.frps worker1 --follow', task_id='follow-1')
    channel = ClientSessionCommandChannel(conn)
    reply = channel.send_command('', type='control', domain=ControlDomain.EXTERNAL_TOOL,
        action=A.READ_INSTANCE_LOGS, payload={
            'tool_id': 'frp.frps', 'package_id': 'frp',
            'module_id': 'frps', 'instance_id': 'worker1'},
        link_foreground_cancel=True)
    assert conn.runtime.get_foreground_task()['command_id'] == 1
    events = list(reply)
    assert events[-1].event['event_type'] == 'completed'
    assert conn.runtime.get_foreground_task()['command_id'] is None
    assert conn.runtime.get_foreground_task()['task_id'] == 'follow-1'
    assert len(conn.sent) == 1 and conn.sent[0]['type'] == 'control'

