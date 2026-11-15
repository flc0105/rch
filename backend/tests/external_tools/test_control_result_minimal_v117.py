"""All 17 External Tool Results carry only fields needed by current consumers."""
from types import SimpleNamespace

import pytest

from client.external_tools import control as client_control
from core.external_tools.payload import client_control_request
from core.protocol.control import ExternalToolAction as A

RICH = {
    'tool_id': 'gost.socks5', 'package_id': 'gost', 'module_id': 'socks5',
    'instance_id': 'rch-wire-116', 'status': 'stopped', 'running': False, 'pid': None,
    'params': {'listen_port': 49178}, 'stdout': '/managed/stdout.log',
    'pid_file': '/managed/tool.pid', 'state_file': '/managed/state.json',
    'stderr': 'stdout', 'argv': ['gost', '-L'], 'cwd': '/managed',
    'started_at': 'today', 'stopped_at': 'today', 'config': {'target': '/managed/demo.conf', 'size': 120},
    'install': {'install_dir': '/managed', 'install_log': 'X' * 100000,
                'cache': {'cache_path': '/archive.zip', 'size': 12000000}},
    'runtime': {'argv': ['gost', '-L'], 'cwd': '/managed', 'pid_file': '/managed/tool.pid'},
    'side': 'client', 'display_name': 'GOST SOCKS5', 'version': '3.2.6',
    'source': 'unnecessary', 'package': {'download_url': '/archive'},
    'message': 'stop requested', 'stop_result': {'sent': True, 'already_stopped': False},
    'removed': True, 'cleared': True, 'cache_removed': True, 'installed': True,
}

@pytest.fixture
def fake(monkeypatch):
    class FakeService:
        def __init__(self, scope):
            pass
        def install_payload(self, payload):
            return dict(RICH)
        def uninstall_payload(self, payload):
            return {**RICH, 'installed': False}
        def install_statuses_payload(self, payload):
            return {'items': [{**RICH, 'install_status': 'installed', 'executable_path': '/managed/gost',
                               'package_key': 'darwin-arm64', 'install_dir': '/managed/gost', 'exec_paths': {'gost': '/managed/gost'},
                               'commands': {'gost': 'gost'}, 'install_log': 'log',
                               'install_log_path': '/managed/.install.log',
                               'cache': {'exists': True, 'cached': True, 'cache_dir': '/cache',
                                         'cache_path': '/cache/archive.zip', 'size': 40, 'mtime': 'today'}}
                              for _ in payload['tools']]}
        def clear_cache_payload(self, payload):
            return dict(RICH)
        def create_instance_payload(self, payload):
            return {**RICH, 'status': 'created', 'running': False}
        def read_instance_definition_payload(self, payload):
            return dict(RICH)
        def instance_log_chunk_payload(self, payload):
            return {'content': 'hello\n', 'cursor': 'a:b:9', 'reset': False, 'running': False}
        def start_payload(self, payload):
            return {**RICH, 'running': True, 'status': 'running'}
        def stop_payload(self, payload):
            return dict(RICH)
        def status_from_payload(self, payload):
            return {'running': True}
        def list_instances_all_payload(self, payload):
            return {'items': [dict(RICH)], 'by_tool': {'gost.socks5': [dict(RICH)]}}
        def remove_instance_payload(self, payload):
            return dict(RICH)
        def clear_logs_payload(self, payload):
            return dict(RICH)
        def preview_payload(self, payload):
            return {**RICH, 'shell': 'sh', 'shell_command': 'cd /managed && gost',
                    'command': 'gost'}
        def oneshot_payload(self, payload):
            return {**RICH, 'success': True, 'status': 'completed', 'returncode': 0,
                    'stdout': 'hello', 'stderr': '', 'duration_sec': 0.1, 'run_id': 'run1'}
        def execute_cli_payload(self, payload):
            return 1, {'status': 'success', 'message': 'version printed'}
        def _instance_definition_path(self, payload):
            return '/managed/instance.json'
    monkeypatch.setattr(client_control, 'ExternalToolClientService', FakeService)
    monkeypatch.setattr(client_control.ExternalToolControl, '_instance_payload', staticmethod(lambda svc, payload: payload))
    monkeypatch.setattr(client_control.ExternalToolControl, '_check_start_paths', staticmethod(lambda svc, payload: None))
    monkeypatch.setattr(client_control, 'resolve_external_tool_launcher', lambda launcher: {
        'type': 'client_python', 'executable': '/usr/bin/python3',
        'command_argv': ['/usr/bin/python3'], 'prefix_args': ['-B'],
    })
    command = SimpleNamespace(bind_execution=lambda *_: None)
    runtime = SimpleNamespace(command_variable_resolver=SimpleNamespace(resolve=lambda value: value),
                              command_executor=SimpleNamespace(get_commands=lambda: command))
    return client_control.ExternalToolControl(runtime)

@pytest.mark.parametrize('action', list(A))
def test_all_actions_wire_result_has_no_internal_execution_state(fake, action):
    payload = dict(RICH)
    if action in (A.GET_INSTALL_STATUSES, A.LIST_INSTANCES):
        payload['tools'] = [dict(RICH)]
    if action == A.RUN_ONESHOT:
        payload['execution'] = 'oneshot'
    scope = SimpleNamespace(command_id=1, execution_context=None)
    code, event = fake.execute(scope, action, payload)
    assert code == 1, (action, event)
    assert event['event_type'] == 'completed' and event['status'] == 'success'
    assert set(event) in ({'event_type', 'status', 'message'}, {'event_type', 'status', 'message', 'data'})
    if action in (A.INSTALL_PACKAGE, A.UNINSTALL_PACKAGE, A.CLEAR_PACKAGE_CACHE, A.CREATE_INSTANCE,
                  A.START_INSTANCE, A.STOP_INSTANCE, A.RESTART_INSTANCE, A.REMOVE_INSTANCE,
                  A.CLEAR_INSTANCE_LOGS, A.EXEC):
        assert 'data' not in event, (action, event)
    else:
        data = event['data']
        assert 'install' not in data and 'runtime' not in data and 'package' not in data
        assert 'version' not in data and 'side' not in data
        if action == A.LIST_INSTANCES:
            assert set(data) == {'items'}
            assert data['items'][0]['pid_file'] == '/managed/tool.pid'  # Web Info uses it
            assert 'install' not in data['items'][0] and 'runtime' not in data['items'][0]
        if action == A.GET_INSTALL_STATUSES:
            assert set(data) == {'items'}
            assert set(data['items'][0]) == {'package_id', 'installed', 'executable_path', 'install_status'}
        if action == A.READ_INSTANCE:
            assert data == {'params': {'listen_port': 49178}}
        if action == A.RESOLVE_LAUNCHER:
            assert data == {'executable': '/usr/bin/python3'}
        if action == A.PREVIEW_INSTANCE:
            assert set(data) == {'instance_id', 'shell', 'cwd', 'shell_command'}
        if action == A.RUN_ONESHOT:
            assert set(data) == {'success', 'status', 'returncode', 'stdout', 'stderr', 'duration_sec', 'run_id'}


def test_explicit_single_package_details_preserve_visible_web_fields(fake):
    payload = client_control_request(A.GET_INSTALL_STATUSES, {'tools': [dict(RICH)], 'include_details': True})
    assert payload['include_details'] is True
    code, result = fake.execute(SimpleNamespace(command_id=1, execution_context=None), A.GET_INSTALL_STATUSES, payload)
    assert code == 1
    detail = result['data']['items'][0]
    assert set(detail) == {'package_id', 'installed', 'install_status', 'executable_path',
                           'package_key', 'install_dir', 'exec_paths', 'commands',
                           'install_log', 'install_log_path', 'cache'}
    assert set(detail['cache']) == {'exists', 'cache_path', 'cache_dir', 'size', 'mtime'}
    assert 'install' not in detail and 'runtime' not in detail


def test_web_lifecycle_and_terminal_both_consume_message_only_success(monkeypatch):
    from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService
    from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
    from pathlib import Path
    metas = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas'
    catalog = ExternalToolCatalogService(str(metas), str(metas.parent / 'packages'))
    events = []
    runtime = ExternalToolRuntimeService(catalog, command_execution_api=None,
                                         event_bus=SimpleNamespace(publish=lambda name, data: events.append((name, data))))
    lifecycle = runtime.client_lifecycle_runtime
    monkeypatch.setattr(lifecycle.payload_builder, 'build_client_start_payload', lambda *args, **kwargs: dict(RICH))
    monkeypatch.setattr(lifecycle.payload_builder, 'build_client_action_payload', lambda *args, **kwargs: dict(RICH))
    monkeypatch.setattr(lifecycle, '_run_client_control', lambda *args, **kwargs: {'message': 'Instance started' if args[1] == A.START_INSTANCE else 'Instance stopped'})
    started = lifecycle.start_client_instance('client', 'gost.socks5', instance_id='rch-wire-116')
    stopped = lifecycle.stop_client_instance('client', 'gost.socks5', 'rch-wire-116')
    assert started == {'message': 'Instance started'}
    assert stopped == {'message': 'Instance stopped'}
    assert [e[1]['state'] for e in events] == ['started', 'stopped']
    assert [e[1]['operation'] for e in events] == ['start', 'stop']
