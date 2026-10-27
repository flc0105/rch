from types import SimpleNamespace

from client.commands.runtime.command_variable_resolver import CommandVariableResolver
from client.runtime.client_info_builder import ClientInfoBuilder


def test_launch_mode_and_detail_variables_share_the_client_launch_snapshot(monkeypatch):
    identity = SimpleNamespace(os_alias='mac')
    monkeypatch.setattr(ClientInfoBuilder, '_get_launch_context', classmethod(
        lambda cls, os_alias: {'mode': 'user_service', 'source': 'launchagent'}
    ))
    resolver = CommandVariableResolver(SimpleNamespace(client_id='client-1'))
    monkeypatch.setattr(resolver, '_get_local_identity', lambda: identity)

    assert resolver.resolve('${rch:launch_mode}|${rch:launch_detail}') == 'user_service|launchagent'
    manifest = resolver.get_manifest_payload()
    rch_names = {item['name'] for item in manifest if item['namespace'] == 'rch'}
    assert {'launch_mode', 'launch_detail'} <= rch_names
    assert len(rch_names) == 25
    assert 'launch_source' not in rch_names


def test_launch_detail_can_be_empty_when_detection_has_no_specific_detail(monkeypatch):
    identity = SimpleNamespace(os_alias='linux')
    monkeypatch.setattr(ClientInfoBuilder, '_get_launch_context', classmethod(
        lambda cls, os_alias: {'mode': 'unknown', 'source': ''}
    ))
    resolver = CommandVariableResolver(SimpleNamespace(client_id='client-1'))
    monkeypatch.setattr(resolver, '_get_local_identity', lambda: identity)

    assert resolver.resolve('${rch:launch_mode}') == 'unknown'
    assert resolver.resolve('${rch:launch_detail}') == ''
