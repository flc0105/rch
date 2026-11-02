"""Package, Module and persistent Instance CLI routing and Client storage."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.protocol.structured_arg_codec import decode_structured_arg
from client.external_tools.service import ExternalToolClientService
from server.application.command.external_tool_cli_builtin_support import ExternalToolCliBuiltinSupport
from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY

METAS = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas'


class Cli(ExternalToolCliBuiltinSupport):
    def __init__(self):
        self.catalog = ExternalToolCatalogService(str(METAS), str(METAS.parent / 'packages'))
        self.runtime = ExternalToolRuntimeService(self.catalog, command_execution_api=None)
        self.conn = SimpleNamespace(session_info=SimpleNamespace(os_alias='win', arch='amd64', cwd='C:/'),
                                    get_foreground_task=lambda: {})
        self.server = SimpleNamespace(web_service=SimpleNamespace(assembly=SimpleNamespace(
            external_tool_catalog_service=self.catalog,
            external_tool_runtime_service=self.runtime,
            external_tool_param_preset_store=SimpleNamespace(list_presets=lambda _: [
                {'name': 'office', 'preset_id': 'abc', 'params': {'server_addr': '192.0.2.1'}}
            ]),
        )))
        self.command_processor_factory = None
        self.history_entry_id_provider = lambda: ''
        self.calls = []
        self.definitions = {}
        self.running_instances = set()
        self.installed = False

    def _nested_json(self, command, payload):
        self.calls.append((command, payload))
        if command == 'external_tool_install_statuses':
            return {'items': [{'installed': idx % 2 == 0, 'install_status': 'installed' if idx % 2 == 0 else 'not_installed'}
                              for idx, _ in enumerate(payload['tools'])]}
        if command == 'external_tool_install_status':
            return {'installed': self.installed, 'install_status': 'installed' if self.installed else 'not_installed'}
        if command == 'external_tool_instance_create':
            key = (payload['tool_id'], payload['instance_id'])
            if key in self.definitions:
                raise ValueError('duplicate instance')
            self.definitions[key] = {'params': payload['params']}
            return {'status': 'created'}
        if command == 'external_tool_instance_read':
            return self.definitions[(payload['tool_id'], payload['instance_id'])]
        if command == 'external_tool_start':
            key = (payload['tool_id'], payload['instance_id'])
            was_running = key in self.running_instances
            self.running_instances.add(key)
            return {'running': True, 'pid': 101, 'message': 'already running' if was_running else 'started'}
        if command == 'external_tool_stop':
            key = (payload['tool_id'], payload['instance_id'])
            was_running = key in self.running_instances
            self.running_instances.discard(key)
            return {'running': False, 'stop_result': {'already_stopped': not was_running}}
        if command == 'external_tool_status':
            running = (payload['tool_id'], payload['instance_id']) in self.running_instances
            return {'status': 'running' if running else 'created', 'running': running, 'pid': 101 if running else None}
        if command == 'external_tool_list_instances_all':
            return {'items': [{'tool_id': tool, 'instance_id': inst, 'status': 'created'} for tool, inst in self.definitions]}
        if command == 'external_tool_instance_logs':
            return {'running': False, 'cursor': 'x', 'content': 'hello log\n'}
        if command == 'external_tool_install':
            self.installed = True
            return {'installed': True, 'already_installed': False, 'message': 'installed'}
        if command == 'external_tool_uninstall':
            self.installed = False
            return {'installed': False, 'removed': True, 'message': 'uninstalled'}
        raise AssertionError(command)


def test_package_and_module_subcommands():
    cli = Cli()
    _, data = next(cli.xt('package list --json'))
    rows = json.loads(data)
    assert rows and all(set(row) == {'package_id', 'display_name', 'installed'} for row in rows)
    _, filtered = next(cli.xt('package list -i --json'))
    assert json.loads(filtered) and all(row['installed'] for row in json.loads(filtered))
    assert next(cli.xt('package install frp')) == (1, 'installed')
    assert cli.calls[-1][0] == 'external_tool_install'
    with pytest.raises(ValueError, match='already installed'):
        list(cli.xt('package install frp'))
    assert next(cli.xt('package uninstall frp')) == (1, 'uninstalled')
    assert cli.calls[-1][0] == 'external_tool_uninstall'
    with pytest.raises(ValueError, match='not installed'):
        list(cli.xt('package uninstall frp'))
    _, modules = next(cli.xt('module list frp --json'))
    assert {'frp.frps', 'frp.frpc', 'frp.frpc_socks5'} == {row['module_id'] for row in json.loads(modules)}
    for invalid in ('package run frp', 'package install', 'module list', 'package list -q'):
        with pytest.raises((ValueError, FileNotFoundError)):
            list(cli.xt(invalid))
    assert [item.name for item in SERVER_COMMAND_REGISTRY.get('xt').subcommands] == ['exec', 'package', 'module', 'instance']


def test_instance_create_start_stop_restart_status_logs_and_preset():
    cli = Cli()
    assert next(cli.xt('instance create frp.frpc --id office-frpc --preset office --params \'{"server_port":7002}\''))[0] == 1
    created = cli.calls[-1][1]
    assert cli.calls[-1][0] == 'external_tool_instance_create'
    assert created['params']['instance_name'] == 'office-frpc'
    assert created['params']['server_addr'] == '192.0.2.1'
    assert created['params']['server_port'] == 7002
    assert next(cli.xt('instance start frp.frpc office-frpc'))[0] == 1
    assert cli.calls[-2][0] == 'external_tool_start'
    assert cli.calls[-1][0] == 'external_tool_status'
    _, status = next(cli.xt('instance status frp.frpc office-frpc --json'))
    assert json.loads(status)['running'] is True
    assert next(cli.xt('instance stop frp.frpc office-frpc'))[0] == 1
    with pytest.raises(ValueError, match='already stopped'):
        list(cli.xt('instance stop frp.frpc office-frpc'))
    with pytest.raises(ValueError, match='already stopped'):
        list(cli.xt('instance restart frp.frpc office-frpc'))
    assert next(cli.xt('instance start frp.frpc office-frpc'))[0] == 1
    with pytest.raises(ValueError, match='already running'):
        list(cli.xt('instance start frp.frpc office-frpc'))
    assert next(cli.xt('instance restart frp.frpc office-frpc'))[0] == 1
    assert next(cli.xt('instance logs frp.frpc office-frpc')) == (1, 'hello log\n')
    _, listing = next(cli.xt('instance list frp --json'))
    assert json.loads(listing)[0]['instance_id'] == 'office-frpc'
    assert json.loads(next(cli.xt('instance list python-embed --json'))[1]) == []
    with pytest.raises(ValueError, match='invalid|Instance ID'):
        list(cli.xt('instance create frp.frpc --id ../../escape'))
    with pytest.raises(ValueError, match='daemon'):
        list(cli.xt('instance create python-embed.test --id demo'))
    with pytest.raises(ValueError, match='duplicate'):
        list(cli.xt('instance create frp.frpc --id office-frpc'))
    assert next(cli.xt('instance create frp.frps --id frps-9 --start'))[0] == 1


def test_client_persistent_instance_definition_and_log_cursor(tmp_path, monkeypatch):
    import client.external_tools.daemon_instance as daemon
    monkeypatch.setattr(daemon, 'EXTERNAL_TOOLS_RUNTIME_ROOT', str(tmp_path))
    client = ExternalToolClientService(SimpleNamespace())
    client.validate_package_payload = lambda *_: ('win', 'amd64')
    payload = {'tool_id': 'frp.frpc', 'package_id': 'frp', 'module_id': 'frpc',
               'instance_id': 'office-frpc', 'params': {'server_addr': '127.0.0.1'}}
    result = client.create_instance_payload(payload)
    assert result['status'] == 'created'
    assert client.read_instance_definition_payload(payload)['params'] == payload['params']
    expected = tmp_path / 'frp/frpc/instances/office-frpc/instance.json'
    assert expected.is_file()
    assert client.list_instances_payload(payload)['items'][0]['status'] == 'created'
    log = expected.with_name('stdout.log')
    log.write_text('hello\n', encoding='utf-8')
    first = client.instance_log_chunk_payload(payload)
    assert first['content'] == 'hello\n' and first['cursor']
    with log.open('a') as stream:
        stream.write('second\n')
    assert client.instance_log_chunk_payload({**payload, 'cursor': first['cursor']})['content'] == 'second\n'
    with pytest.raises(FileExistsError):
        client.create_instance_payload(payload)
    with pytest.raises(ValueError):
        client.create_instance_payload({**payload, 'instance_id': '../evil'})
    # A Web-created daemon has state.json but no instance.json; commands share it.
    web = {**payload, 'instance_id': 'web-instance'}
    state = expected.parents[0].parent / 'web-instance/state.json'
    state.parent.mkdir()
    state.write_text(json.dumps({**web, 'last_status': 'stopped'}), encoding='utf-8')
    assert client.read_instance_definition_payload(web)['params'] == web['params']


def test_instance_status_json_omits_saved_parameters_and_follow_cancels():
    cli = Cli()
    next(cli.xt("instance create frp.frpc --id secure --params '{\"server_addr\":\"secret.example\"}'"))
    _, output = next(cli.xt('instance status frp.frpc secure --json'))
    summary = json.loads(output)
    assert set(summary) == {'module_id', 'instance_id', 'status', 'running', 'pid', 'started_at', 'stopped_at'}
    assert 'secret.example' not in output
    cli.conn.get_foreground_task = lambda: {'cancel_requested': True}
    cli._nested_json_original = cli._nested_json
    def read_running(command, payload):
        if command == 'external_tool_instance_logs':
            return {'running': True, 'content': 'following\n', 'cursor': 'abc'}
        return cli._nested_json_original(command, payload)
    cli._nested_json = read_running
    assert list(cli.xt('instance logs frp.frpc secure -f')) == [(0, 'command cancelled')]


def test_xt_management_completion_package_and_daemon_names():
    from unittest.mock import patch
    import sys
    from core.command_completion.parser import CommandCompletionParser
    info = SimpleNamespace(os_alias='win', arch='amd64')
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _: SimpleNamespace(session_info=info))
    with patch.dict(sys.modules, {'server.config.config': SimpleNamespace(SCRIPT_PATH='', COMMAND_HISTORY_RECENT_LIMIT=30)}):
        from server.application.completion.command_completion_providers import ExternalToolCommandCompletionProvider
    provider = ExternalToolCommandCompletionProvider(server, Cli().catalog)
    parser = CommandCompletionParser()
    def texts(prefix):
        return [item.insert_text for item in provider.complete(parser.parse(prefix, metadata={'client_id': 'c'}))]
    assert 'xt package install frp' in texts('xt package install ')
    assert 'xt package uninstall frp' in texts('xt package uninstall ')
    assert 'xt module list frp' in texts('xt module list ')
    assert 'xt instance start frp.frpc' in texts('xt instance start ')
    assert 'xt instance create frp.frpc' in texts('xt instance create ')
    assert 'xt instance create python-embed.test' not in texts('xt instance create ')


def test_xt_actions_emit_existing_lifecycle_events_and_reject_noops():
    cli = Cli()
    events = []
    cli.conn.session_info.client_id = 'test-client'
    cli.runtime.client_lifecycle_runtime.event_bus = SimpleNamespace(
        publish=lambda name, data: events.append((name, data)))
    list(cli.xt('package install frp'))
    assert events[-1][0] == 'external_tool_lifecycle'
    assert (events[-1][1]['action'], events[-1][1]['state']) == ('install', 'completed')
    with pytest.raises(ValueError, match='already installed'):
        list(cli.xt('package install frp'))
    assert (events[-1][1]['action'], events[-1][1]['state']) == ('install', 'failed')
    assert [action for action, _ in cli.calls].count('external_tool_install') == 1
    list(cli.xt('package uninstall frp'))
    assert (events[-1][1]['action'], events[-1][1]['state']) == ('uninstall', 'completed')
    with pytest.raises(ValueError, match='not installed'):
        list(cli.xt('package uninstall frp'))
    assert (events[-1][1]['action'], events[-1][1]['state']) == ('uninstall', 'failed')
    assert [action for action, _ in cli.calls].count('external_tool_uninstall') == 1
    list(cli.xt('instance create frp.frps --id demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('created', 'create')
    list(cli.xt('instance start frp.frps demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('started', 'start')
    with pytest.raises(ValueError, match='already running'):
        list(cli.xt('instance start frp.frps demo-xt'))
    assert events[-1][1]['state'] == 'error'
    list(cli.xt('instance restart frp.frps demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('started', 'restart')
    list(cli.xt('instance stop frp.frps demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('stopped', 'stop')
    with pytest.raises(ValueError, match='already stopped'):
        list(cli.xt('instance stop frp.frps demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('error', 'stop')
    assert [action for action, _ in cli.calls].count('external_tool_stop') == 2
    prior = len(events)
    list(cli.xt('instance create frp.frps --id another-xt --start'))
    assert [(e['state'], e['operation']) for _, e in events[prior:]] == [('created', 'create'), ('started', 'create')]


def test_xt_follow_cancel_is_local_and_never_sends_unsupported_client_cancel():
    from server.application.tasks.task_service import WebTaskService
    service = object.__new__(WebTaskService)
    requests = []
    service.task_store = SimpleNamespace(request_cancel=lambda task_id: requests.append(task_id))
    task = {'command': 'xt instance logs frp.frps demo --follow', 'cancel_requested': False}
    sent = []
    conn = SimpleNamespace(get_foreground_task=lambda: task,
                           request_foreground_task_cancel=lambda task_id: (
                               task.__setitem__('cancel_requested', True) or {'command_id': 21}),
                           send_cancel=lambda cid: sent.append(cid))
    service._ensure_active_task = lambda conn, task_id: task
    result = service._request_task_cancel(conn, 'task-1')
    assert result['command_id'] == 21 and requests == ['task-1']
    assert task['cancel_requested'] is True and sent == []
    task['command'] = 'xt instance status frp.frps demo'
    task['cancel_requested'] = False
    service._request_task_cancel(conn, 'task-2')
    assert sent == [21]
    assert service._is_server_owned_xt_log_follow('xt instance logs frp.frps demo -f')
    assert not service._is_server_owned_xt_log_follow('xt instance logs frp.frps demo')


def test_xt_instance_creation_notification_uses_prefs_projector():
    from server.application.preferences.notification_event_projector import NotificationEventProjector
    from server.application.preferences.notification_preference_store import NotificationPreferenceStore
    projector = object.__new__(NotificationEventProjector)
    projector.server = SimpleNamespace(get_target_connection_by_client_id=lambda _: SimpleNamespace(
        session_info=SimpleNamespace(hostname='test-host')))
    notification = projector._build_external_tool_lifecycle({
        'action': 'daemon', 'state': 'created', 'operation': 'create',
        'client_id': 'client-1', 'tool_id': 'frp.frps', 'instance_id': 'demo-xt',
        'display_name': 'FRP'})
    assert notification['notification_key'] == 'external_tool_daemon_created'
    prefs = object.__new__(NotificationPreferenceStore)
    prefs.settings = SimpleNamespace(read=lambda: {'enabled': True, 'events': {
        'external_tool_daemon_created': False}})
    assert prefs.is_delivery_enabled(notification['notification_key']) is False
    prefs.settings = SimpleNamespace(read=lambda: {'enabled': True, 'events': {
        'external_tool_daemon_created': True}})
    assert prefs.is_delivery_enabled(notification['notification_key']) is True


def test_xt_unknown_package_status_never_performs_unverified_action():
    cli = Cli()
    original = cli._nested_json
    def unknown_status(command, payload):
        if command == 'external_tool_install_status':
            return {'install_status': 'unknown', 'error': 'offline'}
        return original(command, payload)
    cli._nested_json = unknown_status
    with pytest.raises(RuntimeError, match='Cannot verify installation status'):
        list(cli.xt('package install frp'))
    with pytest.raises(RuntimeError, match='Cannot verify installation status'):
        list(cli.xt('package uninstall frp'))
    assert not any(c[0] in ('external_tool_install', 'external_tool_uninstall') for c in cli.calls)


def test_xt_detects_immediate_process_exit_after_start():
    cli = Cli()
    list(cli.xt('instance create frp.frps --id short-lived'))
    original = cli._nested_json
    def exited(command, payload):
        result = original(command, payload)
        if command == 'external_tool_status' and cli.running_instances:
            return {'running': False, 'status': 'stopped'}
        return result
    cli._nested_json = exited
    with pytest.raises(RuntimeError, match='exited immediately'):
        list(cli.xt('instance start frp.frps short-lived'))
