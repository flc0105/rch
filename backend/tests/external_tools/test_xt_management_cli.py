"""Package, Module and persistent Instance CLI routing and Client storage."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.protocol.control import ExternalToolAction as A
from client.external_tools.service import ExternalToolClientService
from server.application.command.external_tool_cli_builtin_support import ExternalToolCliBuiltinSupport
from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.connection.client_session import ClientSession

METAS = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas'


class Cli(ExternalToolCliBuiltinSupport):
    def __init__(self):
        self.catalog = ExternalToolCatalogService(str(METAS), str(METAS.parent / 'packages'))
        self.runtime = ExternalToolRuntimeService(self.catalog, command_execution_api=None)
        # Exercise the real session interface; a fake direct binding method
        # would hide an XT log-follow connection API mismatch.
        self.conn = ClientSession(SimpleNamespace(send=lambda _: None), {
            'id': 'test-client', 'os_alias': 'win', 'arch': 'amd64', 'cwd': 'C:/',
        })
        self.server = SimpleNamespace()
        self.catalog_service = self.catalog
        self.runtime_service = self.runtime
        self.param_preset_store = SimpleNamespace(list_presets=lambda _: [
            {'name': 'office', 'preset_id': 'abc', 'params': {'server_addr': '192.0.2.1'}}
        ])
        self.command_processor_factory = None
        self.history_entry_id_provider = lambda: ''
        self.calls = []
        self.definitions = {}
        self.running_instances = set()
        self.installed = False

    def run(self, command):
        return self.xt(SERVER_COMMAND_REGISTRY.parse_invocation("xt", command))

    def _nested_json(self, command, payload):
        self.calls.append((command, payload))
        if command == A.GET_INSTALL_STATUSES:
            tools = payload['tools']
            if len(tools) == 1 and tools[0].get('package_id') == 'frp':
                return {'items': [{'installed': self.installed,
                                   'install_status': 'installed' if self.installed else 'not_installed'}]}
            return {'items': [{'installed': idx % 2 == 0,
                               'install_status': 'installed' if idx % 2 == 0 else 'not_installed'}
                              for idx, _ in enumerate(tools)]}
        if command == A.CREATE_INSTANCE:
            key = (payload['tool_id'], payload['instance_id'])
            if key in self.definitions:
                raise ValueError('duplicate instance')
            self.definitions[key] = {'params': payload['params']}
            return {'status': 'created'}
        if command == A.READ_INSTANCE:
            return self.definitions[(payload['tool_id'], payload['instance_id'])]
        if command in (A.START_INSTANCE, A.RESTART_INSTANCE):
            key = (payload['tool_id'], payload['instance_id'])
            was_running = key in self.running_instances
            self.running_instances.add(key)
            return {'running': True, 'pid': 101,
                    'message': 'already running' if was_running and command == A.START_INSTANCE else 'started'}
        if command == A.STOP_INSTANCE:
            key = (payload['tool_id'], payload['instance_id'])
            was_running = key in self.running_instances
            self.running_instances.discard(key)
            return {'running': False, 'stop_result': {'already_stopped': not was_running}}
        if command == A.LIST_INSTANCES:
            rows = []
            for spec in payload.get('tools') or []:
                for (tool, inst), _ in self.definitions.items():
                    if tool != spec['tool_id'] or (spec.get('instance_ids') is not None and inst not in spec['instance_ids']):
                        continue
                    running = (tool, inst) in self.running_instances
                    rows.append({'tool_id': tool, 'instance_id': inst,
                                 'status': 'running' if running else 'created', 'running': running,
                                 'pid': 101 if running else None})
            return {'items': rows}
        if command == A.READ_INSTANCE_LOGS:
            return {'running': False, 'cursor': 'x', 'content': 'hello log\n'}
        if command == A.INSTALL_PACKAGE:
            self.installed = True
            return {'installed': True, 'already_installed': False, 'message': 'installed'}
        if command == A.UNINSTALL_PACKAGE:
            self.installed = False
            return {'installed': False, 'removed': True, 'message': 'uninstalled'}
        raise AssertionError(command)

    def _nested_message(self, command, payload):
        return str(self._nested_json(command, payload).get('message') or '')


def test_package_and_module_subcommands():
    cli = Cli()
    _, data = next(cli.run('package list --json'))
    rows = json.loads(data)
    assert rows and all(set(row) == {'package_id', 'display_name', 'installed'} for row in rows)
    _, filtered = next(cli.run('package list -i --json'))
    assert json.loads(filtered) and all(row['installed'] for row in json.loads(filtered))
    assert next(cli.run('package install frp')) == (1, 'installed')
    assert cli.calls[-1][0] == A.INSTALL_PACKAGE
    with pytest.raises(ValueError, match='already installed'):
        list(cli.run('package install frp'))
    assert next(cli.run('package uninstall frp')) == (1, 'uninstalled')
    assert cli.calls[-1][0] == A.UNINSTALL_PACKAGE
    with pytest.raises(ValueError, match='not installed'):
        list(cli.run('package uninstall frp'))
    _, modules = next(cli.run('module list frp --json'))
    assert {'frp.frps', 'frp.frpc', 'frp.frpc_socks5'} == {row['module_id'] for row in json.loads(modules)}
    for invalid in ('package run frp', 'package install', 'module list', 'package list -q'):
        with pytest.raises((ValueError, FileNotFoundError)):
            list(cli.run(invalid))
    assert [item.name for item in SERVER_COMMAND_REGISTRY.get('xt').subcommands] == ['exec', 'package', 'module', 'instance', 'help']


def test_instance_create_start_stop_restart_status_logs_and_preset():
    cli = Cli()
    assert next(cli.run('instance create frp.frpc --id office-frpc --preset office -- --server_port 7002'))[0] == 1
    created = cli.calls[-1][1]
    assert cli.calls[-1][0] == A.CREATE_INSTANCE
    assert created['params']['instance_name'] == 'office-frpc'
    assert created['params']['server_addr'] == '192.0.2.1'
    assert created['params']['server_port'] == 7002
    assert next(cli.run('instance start frp.frpc office-frpc'))[0] == 1
    assert cli.calls[-2][0] == A.START_INSTANCE
    assert cli.calls[-1][0] == A.LIST_INSTANCES
    _, status = next(cli.run('instance status frp.frpc office-frpc --json'))
    assert json.loads(status)['running'] is True
    assert next(cli.run('instance stop frp.frpc office-frpc'))[0] == 1
    with pytest.raises(ValueError, match='already stopped'):
        list(cli.run('instance stop frp.frpc office-frpc'))
    with pytest.raises(ValueError, match='already stopped'):
        list(cli.run('instance restart frp.frpc office-frpc'))
    assert next(cli.run('instance start frp.frpc office-frpc'))[0] == 1
    with pytest.raises(ValueError, match='already running'):
        list(cli.run('instance start frp.frpc office-frpc'))
    assert next(cli.run('instance restart frp.frpc office-frpc'))[0] == 1
    assert next(cli.run('instance logs frp.frpc office-frpc')) == (1, 'hello log\n')
    _, listing = next(cli.run('instance list frp --json'))
    assert json.loads(listing)[0]['instance_id'] == 'office-frpc'
    assert json.loads(next(cli.run('instance list python-embed --json'))[1]) == []
    with pytest.raises(ValueError, match='invalid|Instance ID'):
        list(cli.run('instance create frp.frpc --id ../../escape'))
    with pytest.raises(ValueError, match='daemon'):
        list(cli.run('instance create python-embed.test --id demo'))
    with pytest.raises(ValueError, match='already exists.*xt instance start office-frpc'):
        list(cli.run('instance create frp.frpc --id office-frpc'))
    assert next(cli.run('instance create frp.frps --id frps-9 --start'))[0] == 1


def test_duplicate_create_is_validation_error_without_client_mutation_or_notification():
    cli = Cli()
    events = []
    cli._publish_xt_lifecycle = lambda *args, **kwargs: events.append((args, kwargs))
    assert next(cli.run('instance create frp.frps --id existing')) == (1, 'Created frp.frps/existing')
    calls_before = len([command for command, _ in cli.calls if command == A.CREATE_INSTANCE])
    with pytest.raises(ValueError, match='Instance "existing" already exists for frp.frps'):
        list(cli.run('instance create frp.frps --id existing --start'))
    assert len([command for command, _ in cli.calls if command == A.CREATE_INSTANCE]) == calls_before
    assert not any(command == A.START_INSTANCE for command, _ in cli.calls)
    assert len(events) == 1  # original successful creation only
    # Duplicate names in other modules remain valid (identity is module-scoped).
    assert next(cli.run('instance create frp.frpc --id existing')) == (1, 'Created frp.frpc/existing')


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
    with pytest.raises(FileExistsError, match='already in use.*runtime directory exists.*xt instance start') as duplicate:
        client.create_instance_payload(payload)
    assert '[Errno 17]' not in str(duplicate.value)
    # An unrecognized directory must not be overwritten either.
    conflict = {**payload, 'instance_id': 'orphan'}
    orphan_dir = expected.parent.parent / 'orphan'
    orphan_dir.mkdir()
    (orphan_dir / 'user-data.txt').write_text('keep me', encoding='utf-8')
    with pytest.raises(FileExistsError, match='Instance ID "orphan" is already in use'):
        client.create_instance_payload(conflict)
    assert (orphan_dir / 'user-data.txt').read_text(encoding='utf-8') == 'keep me' 
    with pytest.raises(ValueError):
        client.create_instance_payload({**payload, 'instance_id': '../evil'})
    # A Web-created daemon has state.json but no instance.json; commands share it.
    web = {**payload, 'instance_id': 'web-instance'}
    state = expected.parents[0].parent / 'web-instance/state.json'
    state.parent.mkdir()
    state.write_text(json.dumps({**web, 'last_status': 'stopped'}), encoding='utf-8')
    assert client.read_instance_definition_payload(web)['params'] == web['params']


def test_instance_status_json_omits_parameters_and_follow_reads_bounded_snapshots():
    cli = Cli()
    next(cli.run("instance create frp.frpc --id secure -- --server_addr secret.example"))
    _, output = next(cli.run('instance status frp.frpc secure --json'))
    summary = json.loads(output)
    assert set(summary) == {'module_id', 'instance_id', 'status', 'running', 'pid', 'started_at', 'stopped_at'}
    assert 'secret.example' not in output

    before = len(cli.calls)
    assert list(cli.run('instance logs frp.frpc secure -f')) == [(1, 'hello log\n')]
    assert [command for command, _ in cli.calls[before:]] == [A.READ_INSTANCE_LOGS]
    assert cli.calls[-1][1]['max_bytes'] == 65536

def test_xt_management_completion_package_and_daemon_names():
    from unittest.mock import patch
    import sys
    from core.command_completion.parser import CommandCompletionParser
    info = SimpleNamespace(os_alias='win', arch='amd64')
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _: SimpleNamespace(session_info=info))
    with patch.dict(sys.modules, {'server.config.config': SimpleNamespace(SCRIPT_PATH='', COMMAND_HISTORY_RECENT_LIMIT=30)}):
        from server.application.completion.command_completion_providers import ExternalToolCommandCompletionProvider
    class FakeClientRuntime:
        def client_install_statuses(self, _client_id, packages, **_kwargs):
            return {'items': [{'installed': p['id'] == 'frp'} for p in packages]}

        def list_all_client_instances(self, _client_id, metas):
            return {'items': [{'tool_id': 'frp.frpc', 'instance_id': 'smoke',
                               'status': 'stopped', 'running': False}]}

    provider = ExternalToolCommandCompletionProvider(server, Cli().catalog, FakeClientRuntime())
    parser = CommandCompletionParser()
    def texts(prefix):
        return [item.insert_text for item in provider.complete(parser.parse(prefix, metadata={'client_id': 'c'}))]
    assert 'xt package install frp' not in texts('xt package install ')
    assert 'xt package install gost' in texts('xt package install ')
    assert 'xt package uninstall frp' in texts('xt package uninstall ')
    assert 'xt module list frp' in texts('xt module list ')
    assert 'xt instance start frp.frpc smoke' in texts('xt instance start ')
    assert 'xt instance stop frp.frpc smoke' not in texts('xt instance stop ')
    assert 'xt instance create frp.frpc' in texts('xt instance create ')
    assert 'xt instance create python-embed.test' not in texts('xt instance create ')


def test_xt_actions_emit_existing_lifecycle_events_and_reject_noops():
    cli = Cli()
    events = []
    cli.conn.session_info.client_id = 'test-client'
    cli.runtime.client_lifecycle_runtime.event_bus = SimpleNamespace(
        publish=lambda name, data: events.append((name, data)))
    list(cli.run('package install frp'))
    assert events[-1][0] == 'external_tool_lifecycle'
    assert (events[-1][1]['action'], events[-1][1]['state']) == ('install', 'completed')
    with pytest.raises(ValueError, match='already installed'):
        list(cli.run('package install frp'))
    assert (events[-1][1]['action'], events[-1][1]['state']) == ('install', 'completed')
    assert [action for action, _ in cli.calls].count(A.INSTALL_PACKAGE) == 1
    list(cli.run('package uninstall frp'))
    assert (events[-1][1]['action'], events[-1][1]['state']) == ('uninstall', 'completed')
    with pytest.raises(ValueError, match='not installed'):
        list(cli.run('package uninstall frp'))
    assert (events[-1][1]['action'], events[-1][1]['state']) == ('uninstall', 'completed')
    assert [action for action, _ in cli.calls].count(A.UNINSTALL_PACKAGE) == 1
    list(cli.run('instance create frp.frps --id demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('created', 'create')
    list(cli.run('instance start frp.frps demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('started', 'start')
    with pytest.raises(ValueError, match='already running'):
        list(cli.run('instance start frp.frps demo-xt'))
    assert events[-1][1]['state'] == 'started'
    list(cli.run('instance restart frp.frps demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('started', 'restart')
    list(cli.run('instance stop frp.frps demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('stopped', 'stop')
    with pytest.raises(ValueError, match='already stopped'):
        list(cli.run('instance stop frp.frps demo-xt'))
    assert (events[-1][1]['state'], events[-1][1]['operation']) == ('stopped', 'stop')
    assert [action for action, _ in cli.calls].count(A.STOP_INSTANCE) == 1
    assert [action for action, _ in cli.calls].count(A.RESTART_INSTANCE) == 1
    prior = len(events)
    list(cli.run('instance create frp.frps --id another-xt --start'))
    assert [(e['state'], e['operation']) for _, e in events[prior:]] == [('created', 'create'), ('started', 'create')]


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
        if command == A.GET_INSTALL_STATUSES:
            return {'items': [{'install_status': 'unknown', 'error': 'offline'}]}
        return original(command, payload)
    cli._nested_json = unknown_status
    with pytest.raises(RuntimeError, match='Cannot verify installation status'):
        list(cli.run('package install frp'))
    with pytest.raises(RuntimeError, match='Cannot verify installation status'):
        list(cli.run('package uninstall frp'))
    assert not any(c[0] in (A.INSTALL_PACKAGE, A.UNINSTALL_PACKAGE) for c in cli.calls)


def test_xt_detects_immediate_process_exit_after_start():
    cli = Cli()
    list(cli.run('instance create frp.frps --id short-lived'))
    original = cli._nested_json
    def exited(command, payload):
        result = original(command, payload)
        if command == A.LIST_INSTANCES and cli.running_instances:
            return {'items': [{'running': False, 'status': 'stopped'}]}
        return result
    cli._nested_json = exited
    with pytest.raises(RuntimeError, match='exited immediately'):
        list(cli.run('instance start frp.frps short-lived'))


def test_xt_usage_and_preflight_errors_are_not_lifecycle_notifications():
    cli = Cli()
    events = []
    cli.conn.session_info.client_id = 'test-client'
    cli.runtime.client_lifecycle_runtime.event_bus = SimpleNamespace(
        publish=lambda name, data: events.append((name, data)))
    for command in (
        'instance start frp.frps',
        'instance start frp.frps demo extra',
        'instance stop frp.frps demo extra',
        'instance restart frp.frps demo extra',
        'instance create frp.frps --id',
        'instance create frp.frps --id demo --params broken',
        'package install',
        'package install does-not-exist',
        'package uninstall does-not-exist',
    ):
        with pytest.raises((ValueError, FileNotFoundError)):
            list(cli.run(command))
    assert events == []
    assert not any(c[0] in (A.START_INSTANCE, A.STOP_INSTANCE,
                           A.INSTALL_PACKAGE, A.UNINSTALL_PACKAGE) for c in cli.calls)


def test_xt_runtime_mutation_failure_does_publish_business_notification():
    cli = Cli()
    events = []
    cli.conn.session_info.client_id = 'test-client'
    cli.runtime.client_lifecycle_runtime.event_bus = SimpleNamespace(
        publish=lambda name, data: events.append((name, data)))
    original = cli._nested_json

    def failed_start(command, payload):
        if command == A.START_INSTANCE:
            raise RuntimeError('actual Client start failure')
        return original(command, payload)

    cli._nested_json = failed_start
    list(cli.run('instance create frp.frps --id failure-test'))
    with pytest.raises(RuntimeError, match='actual Client start failure'):
        list(cli.run('instance start frp.frps failure-test'))
    assert [(data['state'], data['operation']) for _, data in events] == [
        ('created', 'create'), ('error', 'start')]

    cli2 = Cli()
    events2 = []
    cli2.conn.session_info.client_id = 'test-client'
    cli2.runtime.client_lifecycle_runtime.event_bus = SimpleNamespace(
        publish=lambda name, data: events2.append(data))
    original2 = cli2._nested_message
    def failed_install(command, payload):
        if command == A.INSTALL_PACKAGE:
            raise RuntimeError('actual Client installer failed')
        return original2(command, payload)
    cli2._nested_message = failed_install
    with pytest.raises(RuntimeError, match='actual Client installer failed'):
        list(cli2.run('package install frp'))
    assert [(data['action'], data['state']) for data in events2] == [('install', 'failed')]


def test_xt_concurrent_noop_result_is_message_only_and_start_conflict_is_rejected():
    cli = Cli()
    events = []
    cli.conn.session_info.client_id = 'test-client'
    cli.runtime.client_lifecycle_runtime.event_bus = SimpleNamespace(
        publish=lambda name, data: events.append(data))
    original = cli._nested_message
    def raced_install(command, payload):
        if command == A.INSTALL_PACKAGE:
            return 'Package installation completed'
        return original(command, payload)
    cli._nested_message = raced_install
    assert next(cli.run('package install frp')) == (1, 'Package installation completed')
    assert [(item['action'], item['state']) for item in events] == [('install', 'completed')]

    cli._nested_message = original
    list(cli.run('instance create frp.frps --id race'))
    events.clear()
    original_json = cli._nested_json
    def raced_start(command, payload):
        if command == A.START_INSTANCE:
            return {'running': True, 'message': 'already running'}
        return original_json(command, payload)
    cli._nested_json = raced_start
    with pytest.raises(ValueError, match='already running'):
        list(cli.run('instance start frp.frps race'))
    assert events == []


def test_instance_short_name_routes_all_operations_and_keeps_qualified_form():
    cli = Cli()
    assert next(cli.run('instance create frp.frps --id xt-test-frps'))[0] == 1
    before = len(cli.calls)
    assert next(cli.run('instance start xt-test-frps'))[0] == 1
    assert cli.calls[before][0] == A.LIST_INSTANCES
    assert ('frp.frps', 'xt-test-frps') in cli.running_instances

    _, status_text = next(cli.run('instance status xt-test-frps --json'))
    assert json.loads(status_text)['module_id'] == 'frp.frps'
    assert next(cli.run('instance logs xt-test-frps')) == (1, 'hello log\n')
    assert list(cli.run('instance logs xt-test-frps --follow')) == [(1, 'hello log\n')]
    assert next(cli.run('instance restart xt-test-frps'))[0] == 1
    assert next(cli.run('instance stop xt-test-frps'))[0] == 1
    assert ('frp.frps', 'xt-test-frps') not in cli.running_instances
    # Fully qualified form remains valid for the same instance.
    assert next(cli.run('instance start frp.frps xt-test-frps'))[0] == 1
    assert next(cli.run('instance stop frp.frps xt-test-frps'))[0] == 1


def test_instance_short_name_ambiguity_is_safe_and_explicit():
    cli = Cli()
    events = []
    cli.conn.session_info.client_id = 'test-client'
    cli.runtime.client_lifecycle_runtime.event_bus = SimpleNamespace(
        publish=lambda name, data: events.append((name, data)))
    list(cli.run('instance create frp.frpc --id shared-id'))
    list(cli.run('instance create frp.frps --id shared-id'))
    before_events = len(events)
    for operation in ('start', 'stop', 'restart', 'status', 'logs'):
        before_calls = len(cli.calls)
        with pytest.raises(ValueError, match=r'Ambiguous instance ID.*frp\.frpc shared-id.*frp\.frps shared-id'):
            list(cli.run(f'instance {operation} shared-id'))
        assert all(name not in (A.START_INSTANCE, A.STOP_INSTANCE, A.RESTART_INSTANCE,
                                A.REMOVE_INSTANCE)
                   for name, _ in cli.calls[before_calls:])
        assert len(events) == before_events
    assert next(cli.run('instance start frp.frps shared-id'))[0] == 1
    assert ('frp.frps', 'shared-id') in cli.running_instances
    assert ('frp.frpc', 'shared-id') not in cli.running_instances


def test_instance_short_name_not_found_and_validation_do_not_mutate():
    cli = Cli()
    with pytest.raises(FileNotFoundError, match='Instance not found on selected Client: unknown'):
        list(cli.run('instance stop unknown'))
    with pytest.raises(ValueError, match='Instance ID'):
        list(cli.run('instance status ../bad'))
    with pytest.raises(ValueError, match='Too many positional arguments for xt instance start'):
        list(cli.run('instance start frp.frps xt-test-frps extra'))
    assert not any(action in (A.START_INSTANCE, A.STOP_INSTANCE, A.RESTART_INSTANCE)
                   for action, _ in cli.calls)


def test_instance_short_name_success_notifications_reference_resolved_module():
    cli = Cli()
    events = []
    cli.conn.session_info.client_id = 'test-client'
    cli.runtime.client_lifecycle_runtime.event_bus = SimpleNamespace(
        publish=lambda name, data: events.append(data))
    list(cli.run('instance create frp.frps --id xt-test-frps'))
    list(cli.run('instance start xt-test-frps'))
    assert (events[-1]['operation'], events[-1]['tool_id'], events[-1]['instance_id']) == (
        'start', 'frp.frps', 'xt-test-frps')
    list(cli.run('instance stop xt-test-frps'))
    assert (events[-1]['operation'], events[-1]['tool_id'], events[-1]['instance_id']) == (
        'stop', 'frp.frps', 'xt-test-frps')


def test_real_xt_package_list_uses_public_runtime_control_transport():
    """Prevent the runtime facade attribute error reported by an actual CLI user."""
    from server.application.execution.command_stream_service import CommandStreamService

    cli = Cli()
    calls = []

    def remote_stream(conn, command, **kwargs):
        calls.append(kwargs)
        items = [{'package_id': item.get('package_id'), 'install_status': 'not_installed', 'installed': False}
                 for item in kwargs['payload']['tools']]
        yield 1, {'event_type': 'completed', 'status': 'success',
                  'message': 'Installation statuses retrieved', 'data': {'items': items}}

    cli.runtime.core.remote_execution_service = SimpleNamespace(
        stream_command=remote_stream,
        command_stream_service=CommandStreamService(server=None),
    )
    cli._nested_json = ExternalToolCliBuiltinSupport._nested_json.__get__(cli)
    status, output = next(cli.run('package list --json'))
    assert status == 1
    rows = json.loads(output)
    assert rows and all('package_id' in row for row in rows)
    assert calls and all(call['action'] == A.GET_INSTALL_STATUSES for call in calls)


def test_gost_real_metadata_cli_double_dash_and_web_payload_builder_share_types():
    """Exercise actual GOST metadata, not a synthetic command-only fixture."""
    cli = Cli()
    assert next(cli.run('instance create --module gost.socks5 --id rch-registry-check '
                        '-- --listen_ip 127.0.0.1 --listen_port 49173')) == (
        1, 'Created gost.socks5/rch-registry-check')
    action, created = cli.calls[-1]
    assert action == A.CREATE_INSTANCE
    assert created['tool_id'] == 'gost.socks5'
    assert created['params']['instance_name'] == 'rch-registry-check'
    assert created['params']['listen_ip'] == '127.0.0.1'
    assert created['params']['listen_port'] == 49173  # metadata integer coercion
    assert next(cli.run('instance start --module gost.socks5 --name rch-registry-check '
                        '-- --listen_port 49174'))[0] == 1
    action, start = next((action, payload) for action, payload in reversed(cli.calls)
                         if action == A.START_INSTANCE)
    assert start['params']['listen_port'] == 49174
    assert cli.definitions[('gost.socks5', 'rch-registry-check')]['params']['listen_port'] == 49173
    assert next(cli.run('instance stop gost.socks5 rch-registry-check')) == (
        1, 'Stopped gost.socks5/rch-registry-check')
