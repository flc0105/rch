"""A zero-setup Script Viewer Action runs a second registered Script."""
import io
import runpy
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.runtime.execution.python_execution.inproc import InProcessPythonExecutionStrategy
from client.runtime.execution.python_execution.subprocess_pipe import SubprocessPipePythonExecutionStrategy

from client.runtime.sdk.context import use_script_sdk_context
from core.protocol.result_envelope import build_result_wire_event
from server.application.command.server_builtin_registry import ServerCommandRegistry
from server.application.scripts.script_run_service import prepare_script_control

ROOT = Path(__file__).resolve().parents[1] / 'server/resources/scripts/test/misc'
PARENT = ROOT / 'json_result_actions_probe.py'
CHILD = ROOT / 'json_result_actions_update.py'
CHILD_NAME = 'test/misc/json_result_actions_update'


def _view():
    events = []
    with use_script_sdk_context(emit_event=lambda data, *, view=None: events.append((data, view))):
        runpy.run_path(str(PARENT))
    assert len(events) == 1
    return events[0]


def _parse(command):
    from core.utils.parsing import split_shell_arguments
    command_name, *tail = split_shell_arguments(command)
    return ServerCommandRegistry().parse_invocation(command_name, ' '.join(tail))


def test_probe_is_ready_to_run_with_no_inputs_or_cleanup():
    data, view = _view()
    assert len(data) == 1
    assert data[0]['name'] == 'Current Python Client'
    assert isinstance(data[0]['pid'], int)
    assert data[0]['checked_at']
    assert '_actions' not in data[0]
    assert [a['label'] for a in view['actions']] == [
        'Run Child + Refresh', 'Run Child (No Refresh)',
        'Run Child + Confirm', 'Inspect PID',
    ]
    assert [a['refresh'] for a in view['actions']] == [True, False, True, False]
    assert [a['confirm'] for a in view['actions']] == [False, False, True, True]
    wire = build_result_wire_event('test', {'event_type': 'chunk', 'data': data, 'view': view})
    assert wire['view'] == view


def test_each_child_action_uses_registered_script_exec_without_arguments():
    data, view = _view()
    for action in view['actions'][:3]:
        invocation = _parse(action['command'])
        assert invocation.command == 'script' and invocation.action == 'exec'
        assert invocation.arguments['name'] == CHILD_NAME
        assert invocation.arguments['params'] == {}


def test_child_script_really_runs_with_no_kwargs_or_file_state():
    output = io.StringIO()
    with redirect_stdout(output):
        runpy.run_path(str(CHILD))
    assert 'Child Script executed successfully' in output.getvalue()
    assert 'Python PID:' in output.getvalue()
    assert 'Executed at:' in output.getvalue()


def test_child_action_uses_metadata_and_existing_script_control():
    data, view = _view()
    invocation = _parse(view['actions'][0]['command'])
    from core.protocol.script_execution import EXECUTION_CONFIG, OUTPUT_CONFIG
    config = {'items': [
        {'key': EXECUTION_CONFIG, 'choices': ['inproc', 'subprocess_pipe'], 'value': 'inproc'},
        {'key': OUTPUT_CONFIG, 'choices': ['collect', 'stream'], 'value': 'collect'},
    ]}
    payload = prepare_script_control(str(ROOT.parents[1]), invocation.arguments['name'],
                                     invocation.arguments['params'], config=config)
    assert payload['script_name'] == CHILD_NAME
    assert payload['params'] == {}
    assert "print('Child Script executed successfully')" in payload['source']


class _Owner:
    def __init__(self):
        self.events = []
        self.process_execution_service = SimpleNamespace(
            build_process_creation_kwargs=lambda: {},
            wait_process_with_cancel_support=lambda proc, timeout=None: proc.wait(timeout=timeout),
            terminate_process=lambda proc: proc.kill(),
            terminate_process_group=lambda proc: proc.kill(),
        )

    def _set_cancel_policy(self, **kwargs):
        pass

    def _register_cancel_handler(self, handler):
        pass

    def _checkpoint(self, **kwargs):
        pass

    def emit_chunk(self, message='', *, data=None, view=None):
        self.events.append({'message': message, 'data': data, 'view': view})


@pytest.mark.parametrize('strategy', [InProcessPythonExecutionStrategy, SubprocessPipePythonExecutionStrategy])
@pytest.mark.parametrize('mode', ['execute_collect', 'execute_stream'])
def test_real_scripts_run_without_preparation_in_both_python_execution_modes(strategy, mode):
    parent = _Owner()
    status, message = getattr(strategy(parent), mode)(PARENT.read_text(encoding='utf-8'), {})
    assert status == 1, message
    assert any(event['view'] and len(event['view']['actions']) == 4 for event in parent.events)

    # Resolve the Action with the real Server registry and Script Metadata before running B.
    parent_view = next(event['view'] for event in parent.events if event['view'])
    invocation = _parse(parent_view['actions'][0]['command'])
    from core.protocol.script_execution import EXECUTION_CONFIG, OUTPUT_CONFIG
    config = {'items': [
        {'key': EXECUTION_CONFIG, 'choices': ['inproc', 'subprocess_pipe'], 'value': 'inproc'},
        {'key': OUTPUT_CONFIG, 'choices': ['collect', 'stream'], 'value': 'collect'},
    ]}
    payload = prepare_script_control(str(ROOT.parents[1]), invocation.arguments['name'],
                                     invocation.arguments['params'], config=config)
    child = _Owner()
    status, message = getattr(strategy(child), mode)(payload['source'], payload['params'])
    assert status == 1, message
    output = message + ''.join(event.get('message') or '' for event in child.events)
    assert 'Child Script executed successfully' in output
