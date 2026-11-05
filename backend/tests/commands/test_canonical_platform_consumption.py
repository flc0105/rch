"""Server product routing uses handshake os_alias, not OS display fields."""

from types import SimpleNamespace
import importlib
import sys

import pytest

from server.application.web.external_tool_request_context import ExternalToolRequestContextApi


def _session(**kwargs):
    return SimpleNamespace(session_info=SimpleNamespace(**kwargs))


def test_alias_manager_reads_formal_platform_alias_only(monkeypatch):
    # Isolate the platform routing method from Server config's unrelated web dependency.
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, 'server.config.config', SimpleNamespace(ALIAS_PATH='/unused'))
        alias_module = importlib.import_module('server.application.command.alias_manager')
    manager = alias_module.AliasManager.__new__(alias_module.AliasManager)
    assert manager.get_platform_for_connection(_session(os_alias='mac', os_type='Windows')) == 'mac'
    assert manager.get_platform_for_connection(_session(os_type='Windows')) == ''


def test_external_tools_require_formal_platform_alias_for_client_target():
    api = ExternalToolRequestContextApi(None, SimpleNamespace(
        get_target_connection_by_client_id=lambda _id: _session(os_alias='win', os_type='macOS', arch='amd64')
    ))
    assert api._client_session_target('device-1')[:2] == ('win', 'amd64')

    api.server = SimpleNamespace(
        get_target_connection_by_client_id=lambda _id: _session(os_type='Windows', arch='amd64')
    )
    with pytest.raises(ValueError, match='missing platform/arch'):
        api._client_session_target('device-1')
