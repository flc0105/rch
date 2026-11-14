"""Verify migrated controls share their services without internal CLI dispatch."""
import json
import subprocess
import sys
from types import SimpleNamespace

from client.config import runtime_config
from client.runtime.client_runtime import ClientRuntime
from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.execution.upload_execution_service import UploadExecutionService
from server.application.web.command_execution_api import WebCommandExecutionApi
from server.application.web.process_control_api import WebProcessControlApi


def test_configuration_watchdog_process_use_independent_controls(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNTIME_CONFIG_PATH', str(tmp_path / 'config.json'))
    for key in runtime_config._RUNTIME_CONFIG_DEFAULTS:
        monkeypatch.setattr(runtime_config, key, getattr(runtime_config, key))
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_KEYS', list(runtime_config._RUNTIME_CONFIG_OVERRIDE_KEYS))
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_PATH', runtime_config._RUNTIME_CONFIG_OVERRIDE_PATH)
    sock = SimpleNamespace(client_id='qa', client_session_token='', info={}, send_result=lambda *args: None)
    runtime = ClientRuntime(sock, features={'pty': False, 'screen_view': False, 'clipboard': False})
    sock.runtime = runtime
    commands = runtime.command_executor.get_commands()
    for name in ('download_path', 'download_paths', 'preview_path', 'receive_file', 'kill_process', 'list_processes', 'list_apps', 'get_process_detail'):
        assert not hasattr(commands, name), name
    def forbidden(*a, **kw):
        raise AssertionError('Control must not instantiate Commands')
    monkeypatch.setattr(runtime.command_executor, 'get_commands', forbidden)
    dispatch = runtime.control_dispatcher.execute
    key = 'SCRIPT_DEFAULT_OUTPUT_MODE'
    assert dispatch(1, 'configuration', 'set', {'key': key, 'value': 'stream'})[0] == 1
    assert not hasattr(commands, 'set')
    status, result = dispatch(11, 'configuration', 'get', {})
    assert status == 1
    assert next(i for i in result['data']['items'] if i['key'] == key)['value'] == 'stream'
    assert dispatch(12, 'configuration', 'set', {'key': key, 'value': 'collect'})[0] == 1
    status, result = dispatch(2, 'configuration', 'get', {})
    assert status == 1 and next(i for i in result['data']['items'] if i['key'] == key)['value'] == 'collect'
    assert dispatch(3, 'configuration', 'set', {'key': key, 'value': 'invalid'})[0] == 0
    assert dispatch(13, 'configuration', 'set', {'key': key, 'value': 'invalid'})[0] == 0
    assert dispatch(4, 'configuration', 'set', {'key': 'SERVER_INBOUND_TIMEOUT_SECONDS', 'value': 0})[0] == 1
    assert runtime_config.SERVER_INBOUND_TIMEOUT_SECONDS == 0
    assert dispatch(5, 'configuration', 'reset', {'key': 'SERVER_INBOUND_TIMEOUT_SECONDS'})[0] == 1
    assert dispatch(6, 'watchdog', 'status', {})[0] == 1
    assert dispatch(7, 'process', 'kill', {'pid': True})[0] == 0
    with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']) as child:
        try:
            status, result = dispatch(8, 'process', 'kill', {'pid': child.pid})
            assert status == 1, result
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.kill()
    assert all(runtime.execution.context_store.get_existing(i) is None for i in range(1, 9))


def test_web_controls_never_construct_command_strings():
    calls = []
    def control(target, domain, action, payload, **kwargs):
        calls.append((target, domain, action, payload))
        return 1, {'message': 'ok', 'items': [], 'store_path': ''}
    service = SimpleNamespace(run_foreground_control=control)
    api = WebCommandExecutionApi(None, remote_execution_service=service)
    api.get_runtime_config('client')
    api.get_watchdog_status('client')
    process = WebProcessControlApi(None, service)
    process.kill_process('client', 321)
    process.kill_app('client', 322)
    assert calls == [('client','configuration','get',{}), ('client','watchdog','status',{}), ('client','process','kill',{'pid':321}), ('client','process','kill',{'pid':322})]


def test_terminal_upload_uses_transfer_and_preserves_cancellation(tmp_path, monkeypatch):
    from types import ModuleType
    config = ModuleType('server.config.config')
    config.SCRIPT_PATH = str(tmp_path)
    config.COMMAND_HISTORY_RECENT_LIMIT = 100
    monkeypatch.setitem(sys.modules, 'server.config.config', config)
    from server.application.command.builtin_command_support import UploadBuiltinSupport
    src = tmp_path / 'sample.txt'
    src.write_text('test')
    sent, created = [], []
    task = {'task_id': 't', 'tab_id': 'tab', 'history_entry_id': 'h'}
    session = SimpleNamespace(session_info=SimpleNamespace(client_id='client', hostname='host'), send=sent.append, get_foreground_task=lambda: task)
    artifact = SimpleNamespace(stage_local_file=lambda *a, **kw: (str(src), src.name), build_upload_temp_download_relative_url=lambda p: '/temp/file', cleanup_upload_temp_file=lambda p: None)
    transfer = SimpleNamespace(create_transfer=lambda **kw: created.append(kw) or {'transfer_id':'transfer'}, get_transfer=lambda tid: {'state':'running','stage':'transferring'}, wait_for_terminal=lambda tid: {'state':'cancelled'})
    service = UploadExecutionService(None, SimpleNamespace(get_connection=lambda target: session), artifact, transfer)
    from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
    result = list(UploadBuiltinSupport(session, service, lambda: 'h').upload(
        SERVER_COMMAND_REGISTRY.parse_invocation('upload', str(src))))
    assert sent == [{'type':'transfer_start','transfer_id':'transfer','operation':'server_to_client_file','payload':{'relative_url':'/temp/file','filename':'sample.txt','save_dir':''}}]
    assert created[0]['metadata']['history_entry_id'] == 'h' and created[0]['metadata']['task_id'] == 't'
    assert result[-1][0] == 0 and result[-1][1]['event_type'] == CommandExecutionEvent.CANCELLED


def test_transfer_completion_reports_actual_path_and_size(tmp_path, monkeypatch):
    from client.runtime.http_transfer.http_file_transfer_service import HttpFileTransferService
    from server.application.transfers.transfer_service import TransferService
    from client.transfers.manager import _TransferTaskOwner
    from client.runtime.execution.context import ExecutionContext
    sent = []
    owner = _TransferTaskOwner(SimpleNamespace(send=sent.append), ExecutionContext(0))
    service = HttpFileTransferService(owner)
    def download(url, path, **kwargs):
        from pathlib import Path
        Path(path).write_bytes(b'payload')
    monkeypatch.setattr(service, 'get_transfer_strategy', lambda: SimpleNamespace(download_file=download))
    monkeypatch.setattr(service.client_api, 'normalize_file_transfer_url', lambda url: url)
    target = tmp_path / 'saved.txt'
    service.download_file_from_http('https://example.invalid/file', str(target), transfer_id='qa')
    assert sent[-1]['state'] == 'completed' and sent[-1]['destination_path'] == str(target)
    assert sent[-1]['total_bytes'] == 7
    store = TransferService(SimpleNamespace(publish=lambda *a, **kw: None))
    transfer = store.create_transfer(client_id='client', direction='server_to_client', filename='saved.txt')
    store.handle_client_update('client', {**sent[-1], 'transfer_id': transfer['transfer_id']})
    assert store.get_transfer(transfer['transfer_id'])['destination_path'] == str(target)
