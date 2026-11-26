"""Lazy Client metadata and runtime logging behavior."""
import logging
from types import SimpleNamespace

import pytest

from client.connection import handshake
from client.session.control import SessionControl
from client.config import runtime_config
from client.config.runtime_config_effects import RuntimeConfigEffects
from core.protocol.control import SessionAction
from core.protocol.message_queue import ResultChunk
from server.application.connection.connection_service import WebConnectionService


def test_handshake_does_not_build_variable_or_file_manifest(monkeypatch):
    identity = SimpleNamespace(os_type='Linux', os_alias='linux', os_full='Linux',
                               os_name='Linux', os_version='6.0', arch='x86_64',
                               manufacturer='', model='', hostname='device',
                               machine_id='mid', fingerprint_basis='basis')
    monkeypatch.setattr(handshake, 'get_local_identity', lambda: identity)
    monkeypatch.setattr(handshake, 'get_chassis_type', lambda: 'desktop')
    monkeypatch.setattr(handshake, 'recover_current_directory', lambda: None)
    monkeypatch.setattr(handshake, 'get_executable_path', lambda: '/bin/python')
    monkeypatch.setattr(handshake, 'get_client_log_path', lambda: '')
    monkeypatch.setattr(handshake, 'get_system_paths', lambda: {})
    monkeypatch.setattr(handshake, 'reported_current_directory', lambda: '/tmp')
    monkeypatch.setattr(handshake, 'check_privilege', lambda: 'User')
    monkeypatch.setattr(handshake, '_get_client_revision_manifest',
                        lambda: {'revision': 'rev', 'files': {'client/a.py': 'digest'}})
    monkeypatch.setattr(handshake.ClientInfoBuilder, '_build_process_info',
                        lambda self, alias: {'username': 'user', 'process_name': 'python'})
    monkeypatch.setattr(handshake.ClientInfoBuilder, '_get_launch_context',
                        classmethod(lambda cls, alias: {'mode': 'terminal', 'source': 'zsh'}))

    class FakeExecutor:
        def get_command_manifest_payload(self):
            return []

        def get_command_variable_manifest(self):
            raise AssertionError('should only query variables on demand')

    result = handshake.ClientInfoBuilder('client-id', FakeExecutor()).build()
    assert result['client_revision'] == 'rev'
    assert 'client_revision_files' not in result
    assert 'variable_manifest' not in result
    for key in ('file_transfer_mode', 'script_default_execution_mode', 'script_default_output_mode'):
        assert key not in result


def test_session_control_queries_metadata_only_on_request(monkeypatch):
    calls = []
    monkeypatch.setattr('client.config.config.CLIENT_SOURCE_REVISION', '')
    monkeypatch.setattr('core.client_revision.build_client_revision_manifest',
                        lambda **options: calls.append(options) or {'files': {'a.py': 'abcd'}})
    manifest = [{'name': 'pid', 'template': '${rch:pid}'}]
    connection = SimpleNamespace(runtime=SimpleNamespace(command_executor=SimpleNamespace(
        get_command_variable_manifest=lambda: manifest)))
    control = SessionControl(connection)
    assert control.execute(None, SessionAction.GET_VARIABLE_MANIFEST, {}) == (1, {'items': manifest})
    assert calls == []
    assert control.execute(None, SessionAction.GET_REVISION_FILES, {}) == (
        1, {'files': {'a.py': 'abcd'}, 'changed_since_start': []})
    assert calls == [{'include_files': True, 'file_stats': None}]


def test_revision_status_only_queries_client_when_outdated(monkeypatch):
    calls = []
    class FakeSession:
        session_info = SimpleNamespace(client_revision='current')
        def send_command(self, *args, **kwargs):
            calls.append(kwargs['action'])
            event = {'event_type': 'completed', 'status': 'success',
                     'data': {'files': {'a.py': 'client'}}}
            return iter([ResultChunk(1, event, True, event=event)])
    session = FakeSession()
    server = SimpleNamespace(get_target_connection_by_client_id=lambda client_id: session)
    service = WebConnectionService(server, None, None)
    monkeypatch.setattr(service, '_build_connection_state', lambda session: 'online')
    include_files = []
    def build_manifest(*, include_files):
        include_files_calls.append(include_files)
        return {'revision': 'current' if same[0] else 'new',
                'files': {'a.py': 'server'} if include_files else {}}
    include_files_calls = []
    same = [True]
    monkeypatch.setattr('server.application.connection.connection_service.build_client_revision_manifest', build_manifest)
    assert service.get_client_revision_status('id')['state'] == 'current'
    assert calls == []
    assert include_files_calls == [False]
    same[0] = False
    result = service.get_client_revision_status('id')
    assert result['changed_files'] == [{'path': 'a.py', 'change': 'modified'}]
    assert include_files_calls == [False, False, True]
    assert calls == [SessionAction.GET_REVISION_FILES]
    # The variable query uses the same typed Session Control response channel.
    session.send_command = lambda *args, **kwargs: iter([
        ResultChunk(1, {'data': {'items': []}}, True,
                    event={'event_type': 'completed', 'status': 'success', 'data': {'items': []}}),
    ])
    assert service.get_variable_manifest('id') == []


def test_runtime_log_level_is_configurable_and_immediate(monkeypatch):
    from client.app.logging import apply_client_log_level
    from core.utils.logger import logger
    root = logging.getLogger()
    original_root_level, original_client_level = root.level, logger.level
    class FakeHandler(logging.NullHandler):
        _rch_client_main_log = True
    handler = FakeHandler()
    root.addHandler(handler)
    try:
        monkeypatch.setattr(runtime_config, 'LOG_LEVEL', 'INFO')
        apply_client_log_level()
        assert root.level == logger.level == handler.level == logging.INFO
        monkeypatch.setattr(runtime_config, 'LOG_LEVEL', 'DEBUG')
        RuntimeConfigEffects(None, lambda: False).apply('LOG_LEVEL', 'DEBUG')
        assert root.level == logger.level == handler.level == logging.DEBUG
        assert RuntimeConfigEffects(None, lambda: False).apply('LOG_LEVEL', 'DEBUG') == []
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(original_root_level)
        logger.setLevel(original_client_level)
