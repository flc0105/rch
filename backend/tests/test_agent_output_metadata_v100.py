"""Canonical Agent Output metadata and strict schema contract."""
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from server.application.agent.agent_output_registry import AgentOutputRegistry
from server.persistence.rch_database import RchDatabase


@pytest.fixture
def catalog(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    directory = tmp_path / 'agent_output'
    registry = AgentOutputRegistry(str(directory), database)
    yield database, registry, directory
    database.close_thread_connection()


def _register(registry, directory, *, builder='go', mode='reverse', transport='mtls_tcp',
              origin='manual', filename='agent.zip'):
    (directory / filename).write_bytes(b'output')
    return registry.register_output({
        'file_name': filename, 'builder': builder,
        'build_version': 'go_20261125_abc12345',
        'target_os': '' if builder == 'python' else 'win',
        'target_arch': '' if builder == 'python' else 'amd64',
    }, source=origin, request_payload={
        'builder': builder,
        'connection_mode': mode,
        'listener_protocol': transport,
        'listener_id': 'listener-A',
        'listener_name': 'Reverse Listener',
        'server_host': '192.168.1.10' if mode == 'reverse' else '',
        'server_port': 9998 if mode == 'reverse' else 9999,
        'bind_host': '0.0.0.0', 'bind_port': 9443,
        'server_web_host': '192.168.1.10' if mode == 'reverse' or builder == 'go_loader' else '',
        'web_port': 8085,
    })


@pytest.mark.parametrize('mode,transport,builder', [
    ('reverse', 'tcp', 'python'),
    ('reverse', 'mtls_tcp', 'go'),
    ('bind', 'tcp', 'go'),
    ('bind', 'mtls_tcp', 'go_loader'),
    ('bind', 'mtls_tcp', 'python'),
])
def test_metadata_records_authentic_endpoints_and_only_meaningful_web(catalog, mode, transport, builder):
    database, registry, directory = catalog
    record = _register(registry, directory, builder=builder, mode=mode, transport=transport)
    assert record['connection_mode'] == mode
    assert record['transport'] == transport
    assert record['endpoint_ip'] == ('192.168.1.10' if mode == 'reverse' else '0.0.0.0')
    assert record['endpoint_port'] == (9998 if mode == 'reverse' else 9443)
    assert record['listener_id'] == ('listener-A' if mode == 'reverse' else '')
    assert record['listener_name'] == ('Reverse Listener' if mode == 'reverse' else '')
    assert record['web_ip'] == ('192.168.1.10' if mode == 'reverse' or builder == 'go_loader' else '')
    assert record['web_port'] == (8085 if mode == 'reverse' or builder == 'go_loader' else 0)
    assert record['target_os'] == ('' if builder == 'python' else 'win')
    assert record['target_arch'] == ('' if builder == 'python' else 'amd64')
    assert record['build_origin'] == 'manual'
    assert record['build_version'] == 'go_20261125_abc12345'
    assert 'version' not in record
    assert record['size'] == 6
    assert registry.list_outputs() == [record]
    columns = {row['name'] for row in database.fetch_all('PRAGMA table_info(agent_outputs)')}
    assert {'connection_mode', 'transport', 'endpoint_ip', 'endpoint_port', 'web_ip', 'web_port',
            'build_version', 'build_origin'} <= columns
    assert 'version' not in columns
    assert not {'source', 'connect_host', 'connect_port', 'web_scheme', 'web_host'} & columns


def test_unused_indexes_removed_and_created_index_retained(catalog):
    database, _, _ = catalog
    indexes = {row['name'] for row in database.fetch_all('PRAGMA index_list(agent_outputs)')}
    assert 'idx_agent_outputs_created' in indexes
    assert 'idx_agent_outputs_listener' not in indexes
    assert 'idx_agent_outputs_source' not in indexes


@pytest.mark.parametrize('bad_field,bad_value', [
    ('connection_mode', 'other'),
    ('listener_protocol', 'tls_tcp'),
    ('bind_port', 0),
])
def test_invalid_metadata_is_rejected_without_persisting(catalog, bad_field, bad_value):
    database, registry, directory = catalog
    payload = {'connection_mode': 'bind', 'listener_protocol': 'mtls_tcp', 'bind_host': '0.0.0.0',
               'bind_port': 9443, 'server_web_host': '', 'web_port': 8085}
    payload[bad_field] = bad_value
    (directory / 'a.zip').write_bytes(b'x')
    with pytest.raises(ValueError):
        registry.register_output({'file_name':'a.zip','builder':'python','build_version':'b'}, request_payload=payload)
    assert not database.fetch_all('SELECT * FROM agent_outputs')


def test_transient_cleanup_reads_renamed_origin(catalog):
    _, registry, directory = catalog
    _register(registry, directory, filename='manual.zip')
    _register(registry, directory, origin='bootstrap', filename='bootstrap.zip')
    _register(registry, directory, origin='update', filename='update.zip')
    snapshot = registry.startup_transient_outputs()
    assert {row['file_name'] for row in snapshot} == {'bootstrap.zip', 'update.zip'}
    registry.get_download_path('bootstrap.zip')
    assert not registry.is_cleanup_output('bootstrap.zip')
    assert registry.is_cleanup_output('update.zip')


def test_schema_refuses_old_layout_without_auto_migration(catalog):
    database, _, _ = catalog
    with database.transaction() as conn:
        conn.execute('DROP TABLE agent_outputs')
        conn.execute('CREATE TABLE agent_outputs (file_name TEXT PRIMARY KEY, builder TEXT)')
    database.close_thread_connection()
    with pytest.raises(RuntimeError, match='incompatible schema for agent_outputs'):
        RchDatabase(database.db_path)


def test_web_agent_api_passes_resolved_transport_and_endpoints(catalog, tmp_path):
    _, registry, directory = catalog
    class FakeBuilder:
        output_dir = str(directory)
        def build_agent(self, **kwargs):
            (directory / 'new.zip').write_bytes(b'build')
            return {'file_name': 'new.zip', 'builder':kwargs['builder'],
                    'build_version':'python_2026_abc', 'target_os':'', 'target_arch':''}
    # Import Web facade without initializing unrelated Web admin authentication.
    config = ModuleType('server.config.config')
    config.SOCKET_PORT = 9999
    config.WEB_PORT = 8085
    config.SERVER_RUNTIME_DIR = str(tmp_path)
    with patch.dict(sys.modules, {'server.config.config': config}):
        from server.application.web.agent_api import WebAgentApi
    api = WebAgentApi(FakeBuilder(), registry, server=SimpleNamespace(listener_manager=None))
    result = api.build_agent('', 9999, 8085, 'mac', 'python', '', 'http', '', 'manual',
                             listener_protocol='mtls_tcp', connection_mode='bind',
                             bind_host='0.0.0.0', bind_port=9445)
    assert result['connection_mode'] == 'bind'
    assert result['transport'] == 'mtls_tcp'
    assert result['endpoint_port'] == 9445
    assert result['web_ip'] == ''
    assert result['web_port'] == 0
    assert api.list_agent_outputs()[0]['download_url'] == '/api/agent/download/new.zip'


def test_reverse_web_ip_falls_back_to_configured_server_ip(catalog):
    _, registry, directory = catalog
    (directory / 'reverse.zip').write_bytes(b'reverse')
    record = registry.register_output({'file_name': 'reverse.zip', 'builder': 'python',
                                       'build_version': 'python_2026_x'}, request_payload={
        'connection_mode': 'reverse', 'listener_protocol': 'tcp',
        'server_host': '192.168.1.99', 'server_port': 9999, 'web_port': 8085,
    })
    assert record['web_ip'] == '192.168.1.99'


def test_build_version_is_the_only_version_field(catalog):
    _, registry, directory = catalog
    (directory / 'version.zip').write_bytes(b'version')
    record = registry.register_output({'file_name':'version.zip', 'builder':'go',
                                       'build_version':'go_2026_x'}, request_payload={
        'connection_mode':'bind', 'listener_protocol':'tcp', 'bind_host':'0.0.0.0',
        'bind_port':9443,
    })
    assert record['build_version'] == 'go_2026_x'
    assert 'version' not in record
