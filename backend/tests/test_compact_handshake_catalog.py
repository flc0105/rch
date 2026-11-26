"""Handshake catalog and Web candidate boundaries use one canonical representation."""
from types import SimpleNamespace

from client.commands.runtime.manifest_metadata import command_metadata
from client.commands.shell.decorators import shell_command
from server.application.web.command_catalog_api import WebCommandCatalogApi
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


def test_handshake_catalog_has_no_redundant_presentation_fields(monkeypatch):
    @shell_command('Demonstrate interaction', group='test', may_interact=True, output='stream')
    def demo(_self):
        return 1, 'ok'

    metadata = command_metadata(demo)
    assert metadata['kind'] == 'command'
    assert demo.command_may_interact is True
    assert demo.command_output == 'stream'
    for name in ('may_interact', 'source', 'suggest', 'timeout', 'interaction', 'output'):
        assert name not in metadata


def test_server_adds_source_only_when_publishing_client_candidates():
    manifest = [
        {'name': 'shell', 'help': 'Run a shell', 'group': 'execution',
         'kind': 'command', 'cancel_policy': 'process'},
        {'name': 'acmd ps', 'help': 'Processes', 'group': 'acmd',
         'kind': 'acmd', 'cancel_policy': 'none', 'completion': [{'provider': 'filesystem', 'kinds': ['directory']}]},
    ]
    fake_session = SimpleNamespace(session_info=SimpleNamespace(command_manifest=manifest))
    facade = WebCommandCatalogApi(None, None)
    result = facade._get_client_command_candidates(fake_session)
    assert [item['source'] for item in result] == ['client', 'client']
    assert [item['kind'] for item in result] == ['command', 'acmd']
    assert result[1]['completion'] == manifest[1]['completion']
    assert result[0]['cancel_policy'] == 'process'
    for item in result:
        for key in ('may_interact', 'suggest', 'timeout', 'interaction', 'output'):
            assert key not in item


def test_server_builtins_keep_source_without_legacy_suggest():
    candidates = SERVER_COMMAND_REGISTRY.candidates()
    assert candidates
    assert all(item['source'] == 'server' and 'suggest' not in item for item in candidates)


def test_override_report_uses_info_level(monkeypatch):
    from client.config import runtime_config_reporter
    from client.config import runtime_config
    calls = []
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_KEYS', ['LOG_LEVEL'], raising=False)
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_PATH', '/tmp/settings.json', raising=False)
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_DEFAULTS', {'LOG_LEVEL': 'INFO'}, raising=False)
    monkeypatch.setattr(runtime_config, 'LOG_LEVEL', 'DEBUG')
    monkeypatch.setattr(runtime_config_reporter, 'logger', SimpleNamespace(
        info=lambda message: calls.append(message),
        warning=lambda message: (_ for _ in ()).throw(AssertionError('must not warn'))))
    runtime_config_reporter.log_runtime_config_overrides_if_any()
    assert len(calls) == 1
    assert 'LOG_LEVEL' in calls[0] and 'Runtime config overrides are active' in calls[0]
