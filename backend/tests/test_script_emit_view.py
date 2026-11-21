"""Script emit_view through both Python strategies and the canonical wire."""
from types import SimpleNamespace

import pytest

from client.runtime.sdk import context
from client.runtime.execution.python_execution.inproc import InProcessPythonExecutionStrategy
from client.runtime.execution.python_execution.subprocess_pipe import SubprocessPipePythonExecutionStrategy
from core.protocol.result_envelope import build_result_wire_event


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
        self.cancel_handler = handler

    def _checkpoint(self, **kwargs):
        pass

    def emit_progress(self, message, *, level=None):
        self.events.append({'event_type': 'progress', 'message': message, 'level': level})

    def emit_chunk(self, message='', *, data=None, view=None):
        event = {'event_type': 'chunk'}
        if data is not None: event['data'] = data
        else: event['message'] = message
        if view is not None: event['view'] = view
        self.events.append(event)


SCRIPT = """from client.runtime.sdk import context
print('before')
context.emit({'ordinary': True})
context.emit_view([{'pid': 4}], view={'actions': [{'label': 'Inspect', 'command': 'getpid', 'confirm': False}]})
print('after')
"""


@pytest.mark.parametrize('strategy', [InProcessPythonExecutionStrategy, SubprocessPipePythonExecutionStrategy])
@pytest.mark.parametrize('method', ['execute_collect', 'execute_stream'])
def test_emit_view_reaches_result_wire_with_original_order(strategy, method):
    owner = _Owner()
    status, message = getattr(strategy(owner), method)(SCRIPT, {})
    assert status == 1, message
    data = [event for event in owner.events if event.get('data') is not None]
    assert len(data) == 2
    assert data[0]['data'] == {'ordinary': True} and 'view' not in data[0]
    assert data[1]['data'] == [{'pid': 4}]
    assert data[1]['view']['actions'][0]['label'] == 'Inspect'
    for event in data:
        assert build_result_wire_event('test', event)['data'] == event['data']
    assert next(i for i, e in enumerate(owner.events) if e.get('message') == 'before') < owner.events.index(data[0])
    assert owner.events.index(data[0]) < owner.events.index(data[1])
    assert owner.events.index(data[1]) < next(i for i, e in enumerate(owner.events) if 'after' in e.get('message', ''))


def test_emit_view_rejects_invalid_metadata_before_publish():
    sent = []
    with context.use_script_sdk_context(emit_event=lambda data, **kwargs: sent.append(data)):
        with pytest.raises(ValueError, match='Invalid Result view action'):
            context.emit_view([{'pid': 1}], view={'actions': [{'label': 'Oops', 'command': ''}]})
        with pytest.raises(TypeError, match='JSON object or array'):
            context.emit_view('not data', view={})
    assert sent == []


def test_emit_view_frozen_and_requires_live_channel():
    original = [{'pid': 1}]
    view = {'actions': [{'label': 'Inspect', 'command': 'getpid'}]}
    sent = []
    with context.use_script_sdk_context(emit_event=lambda data, **kwargs: sent.append((data, kwargs['view']))):
        context.emit_view(original, view=view)
    original[0]['pid'] = 999
    view['actions'][0]['command'] = 'fake'
    assert sent[0][0][0]['pid'] == 1
    assert sent[0][1]['actions'][0]['command'] == 'getpid'
    with pytest.raises(RuntimeError, match='active Script output channel'):
        context.emit_view([{}], view={})
