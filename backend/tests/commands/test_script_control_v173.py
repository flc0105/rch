"""Script UI and terminal submit the same typed Control request with resolved modes."""
import sys
import types
from types import SimpleNamespace

import pytest

from client.runtime.control_dispatcher import ClientControlDispatcher
from client.controls.registration import register_control_domain
from core.protocol.control import ControlDomain, ScriptAction
from client.runtime.execution.runtime import ExecutionRuntime
from client.scripts.manager import ScriptManager
from core.protocol.control import ControlRequest
from server.application.scripts.script_run_service import prepare_script_control


CONFIG = {'items': [
    {'key':'SCRIPT_DEFAULT_EXECUTION_MODE','value':'inproc','choices':['inproc','subprocess_pipe']},
    {'key':'SCRIPT_DEFAULT_OUTPUT_MODE','value':'collect','choices':['collect','stream']},
]}
MODES = {'execution_mode':'inproc','output_mode':'collect'}

SCRIPT_SOURCE = '''SCRIPT_METADATA = {
    "name": "example", "params": [
        {"name": "host", "type": "string", "required": True},
        {"name": "port", "type": "integer", "default": 443},
    ],
}
print(kwargs["host"], kwargs["port"])
'''


def test_script_control_preparation_validates_metadata_once_for_cli_and_ui(tmp_path):
    script = tmp_path / 'folder' / 'ping.py'
    script.parent.mkdir()
    script.write_text(SCRIPT_SOURCE, encoding='utf-8')
    cli = prepare_script_control(str(tmp_path), 'folder/ping.py', {'host': 'example.com', 'port': '80'}, config=CONFIG)
    web = prepare_script_control(str(tmp_path), 'folder/ping', {'host': 'example.com', 'port': 80}, config=CONFIG)
    assert cli == web == {
        'script_name': 'folder/ping', 'source': SCRIPT_SOURCE,
        'params': {'host': 'example.com', 'port': 80}, **MODES,
    }
    assert 'presentation' not in cli
    with pytest.raises(ValueError, match='Missing required'):
        prepare_script_control(str(tmp_path), 'folder/ping', {}, config=CONFIG)
    with pytest.raises(ValueError, match='outside'):
        prepare_script_control(str(tmp_path), '../elsewhere', {}, config=CONFIG)


def test_script_control_client_runs_existing_script_strategy(tmp_path):
    payload = {
        'script_name': 'folder/ping', 'source': SCRIPT_SOURCE,
        'params': {'host': 'example.com', 'port': 80}, **MODES,
    }
    socket = SimpleNamespace()
    manager = ScriptManager()
    control = ClientControlDispatcher(ExecutionRuntime(socket))
    register_control_domain(control, ControlDomain.SCRIPT, manager.execute, cancel_policies={ScriptAction.RUN: manager.cancel_policy})
    assert control.execute(1, 'script', 'run', payload) == (1, 'example.com 80\n')
    assert control.execute(2, 'script', 'bad', payload)[0] == 0
    assert control.execute(3, 'script', 'run', {'source': SCRIPT_SOURCE, 'params': {}})[0] == 0


def test_script_cli_and_web_use_one_payload_and_web_presentation_stays_runtime_only(tmp_path, monkeypatch):
    script = tmp_path / 'folder' / 'ping.py'
    script.parent.mkdir()
    script.write_text(SCRIPT_SOURCE, encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'server.config.config', types.ModuleType('server.config.config'))
    config = sys.modules['server.config.config']
    monkeypatch.setattr(config, 'SCRIPT_PATH', str(tmp_path), raising=False)
    monkeypatch.setattr(config, 'COMMAND_HISTORY_RECENT_LIMIT', 100, raising=False)
    from server.application.command import builtin_command_support
    monkeypatch.setattr(builtin_command_support, 'SCRIPT_PATH', str(tmp_path))
    from server.application.command.builtin_command_support import ScriptBuiltinSupport
    from server.application.web.script_api import WebScriptApi
    from server.application.web.command_execution_api import WebCommandExecutionApi

    cli_plans = []
    builtin = ScriptBuiltinSupport(
        SimpleNamespace(build_script_plan=lambda p: {'command_type': 'control', 'domain': 'script', 'action': 'run', 'payload': p}),
        lambda: (lambda plan: (lambda: (cli_plans.append(plan) or iter([(1, 'completed')])))),
        remote_execution_service=SimpleNamespace(run_foreground_control=lambda *a, **kw: (1, {'data': CONFIG})),
    )
    from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
    invoke = lambda arg: SERVER_COMMAND_REGISTRY.parse_invocation('script', arg)
    assert list(builtin.script(invoke('exec folder/ping.py -- --host example.com --port 80'))) == [(1, 'completed')]
    assert list(builtin.script(invoke('exec --name folder/ping.py --execution_mode subprocess_pipe --output_mode stream -- --host example.com --port 80'))) == [(1, 'completed')]
    assert cli_plans[-1]['payload']['execution_mode'] == 'subprocess_pipe'
    assert cli_plans[-1]['payload']['output_mode'] == 'stream'
    assert cli_plans[-1]['payload']['params'] == {'host': 'example.com', 'port': 80}
    for options in ('--invalid_option inproc', '--execution_mode bad_mode', '--execution_mode inproc --execution_mode subprocess_pipe'):
        with pytest.raises((ValueError, FileNotFoundError)):
            list(builtin.script(invoke('exec ' + options + ' folder/ping.py -- --host example.com')))
    with pytest.raises(ValueError, match='requires 1 value'):
        invoke('exec --name folder/ping.py --execution_mode')
    assert list(builtin.script(invoke('view --name folder/ping.py')))[0][1] == SCRIPT_SOURCE
    assert cli_plans[0]['command_type'] == 'control'
    assert cli_plans[0]['domain'] == 'script' and cli_plans[0]['action'] == 'run'

    web_requests = []

    class Tasks:
        def submit_web_control(self, client_id, command, control, **kwargs):
            web_requests.append((client_id, command, control, kwargs))
            return {'ok': True}

    web_api = WebScriptApi(WebCommandExecutionApi(Tasks()), SimpleNamespace(scripts_root_dir=str(tmp_path)))
    web_api.command_execution_api.get_runtime_config = lambda client_id: {'data': CONFIG}
    assert web_api.run_script('client-a', 'folder/ping.py', {'host': 'example.com', 'port': 80}, presentation='dialog', run_id='r-1') == {'ok': True}
    assert web_requests[0][1] == cli_plans[0]['payload']['script_name']
    assert web_requests[0][2].payload == cli_plans[0]['payload']
    assert web_requests[0][3]['metadata']['script_run_presentation'] == 'dialog'


def test_script_task_dispatches_control_not_a_fake_command(tmp_path, monkeypatch):
    script = tmp_path / 'ping.py'
    script.write_text('print(12)\n', encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'server.config.config', types.ModuleType('server.config.config'))
    config = sys.modules['server.config.config']
    monkeypatch.setattr(config, 'SCRIPT_PATH', str(tmp_path), raising=False)
    monkeypatch.setattr(config, 'COMMAND_HISTORY_RECENT_LIMIT', 100, raising=False)
    from server.application.tasks.task_runner import WebTaskRunner
    runner = object.__new__(WebTaskRunner)
    calls = []

    class Remote:
        def stream_command(self, conn, command, **kwargs):
            calls.append((conn, command, kwargs))
            yield 1, 'printed'

    from server.application.command.command_execution_pipeline import CommandExecutionPipeline
    runner.command_execution_pipeline = CommandExecutionPipeline(None)
    runner.remote_execution_service = Remote()
    runner._get_history_entry_id = lambda context: 'history-1'
    context = SimpleNamespace(
        session=object(), history_entry_id='', command='ping',
        metadata={'script_run_presentation': 'dialog'},
        control=ControlRequest('script', 'run', prepare_script_control(str(tmp_path), 'ping', {}, config=CONFIG)),
    )
    script.write_text('raise RuntimeError("should not reload")\n', encoding='utf-8')
    events = list(runner._iter_control_events(context))
    assert calls[0][1] == ''
    assert calls[0][2]['command_type'] == 'control'
    assert calls[0][2]['domain'] == 'script' and calls[0][2]['action'] == 'run'
    assert calls[0][2]['payload'] == {'script_name': 'ping', 'source': 'print(12)\n', 'params': {}, **MODES}
    assert 'presentation' not in calls[0][2]['payload']
    assert len(events) == 3
