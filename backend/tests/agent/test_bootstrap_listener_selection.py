"""Bootstrap listener selection is optional and preserves default TCP behavior."""
import ast
import json

from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService
from server.application.connection.connection_history_store import ConnectionHistoryStore


def _request_payload_from_python_bootstrap(listener_id):
    service = AgentBootstrapScriptService()
    parameters = {'server_host': '127.0.0.1', 'server_port': 9443 if listener_id else 9999,
                  'web_port': 8085, 'listener_id': listener_id}
    source = service.generate_python_script(parameters)
    ast.parse(source)
    variables = {'__name__': 'bootstrap_test'}
    exec(compile(source, '<bootstrap>', 'exec'), variables)
    seen = []

    def request_bytes(url, payload):
        seen.append(payload)
        return json.dumps({'code': 0, 'data': {'build_version': 'v', 'file_name': 'agent.zip'}}).encode()

    variables['request_bytes'] = request_bytes
    variables['build_bundle']()
    assert len(seen) == 1
    return source, seen[0]


def test_python_tls_bootstrap_forwards_listener_to_existing_build():
    source, payload = _request_payload_from_python_bootstrap('tls-abc123')
    assert 'LISTENER_ID = "tls-abc123"' in source
    assert payload['listener_id'] == 'tls-abc123'
    assert payload['server_port'] == 9443
    assert payload['builder'] == 'bundle'


def test_python_default_tcp_bootstrap_keeps_original_build_payload():
    source, payload = _request_payload_from_python_bootstrap('')
    assert 'LISTENER_ID = ""' in source
    assert 'listener_id' not in payload
    assert payload['server_port'] == 9999


def test_powershell_bootstrap_only_adds_listener_when_selected():
    service = AgentBootstrapScriptService()
    base = {'server_host': '127.0.0.1', 'server_port': 9999, 'web_port': 8085}
    tcp = service.generate_powershell_script(base)
    tls = service.generate_powershell_script({**base, 'server_port': 9443, 'listener_id': 'tls-abc123'})
    assert '$listenerId=""' in tcp
    assert '$listenerId="tls-abc123"' in tls
    assert "if ($listenerId) { $body['listener_id'] = $listenerId }" in tls
    assert tls.index('if ($listenerId)') < tls.index('$body = $body | ConvertTo-Json')


def test_history_snapshot_retains_listener_origin_and_port():
    store = ConnectionHistoryStore(database=None)
    snapshot = store._build_snapshot({'machine_id': 'm1', 'client_id': 'c1',
                                      'listener_id': 'abc', 'listener_name': 'TLS',
                                      'listener_protocol': 'tls_tcp', 'listener_port': 9443})
    assert snapshot['listener_name'] == 'TLS'
    assert snapshot['listener_port'] == 9443
