"""Server command dispatch must not infer session termination from command text."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from server.application.execution.remote_execution_service import RemoteExecutionService
from server.connection.client_session import ClientSession


def _load_executor():
    # Only the unrelated web/auth import is stubbed; the execution path is real.
    path = Path(__file__).resolve().parents[2] / 'server/application/command/executor.py'
    spec = importlib.util.spec_from_file_location('_test_session_dispatch_executor', path)
    module = importlib.util.module_from_spec(spec)
    stub = ModuleType('server.application.command.builtin_command_handler')
    stub.BuiltinCommandHandler = type('UnusedBuiltinCommandHandler', (), {})
    original = sys.modules.get(stub.__name__)
    try:
        sys.modules[stub.__name__] = stub
        spec.loader.exec_module(module)
    finally:
        if original is None:
            sys.modules.pop(stub.__name__, None)
        else:
            sys.modules[stub.__name__] = original
    return module.CommandExecutor


CommandExecutor = _load_executor()


class _Transport:
    address = ('127.0.0.1', 5999)

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)

    def close(self):
        pass


def _executor(guard):
    transport = _Transport()
    session = ClientSession(transport)
    server = SimpleNamespace(command_history_orchestrator=None)
    executor = CommandExecutor.__new__(CommandExecutor)
    executor.conn = session
    executor.server = server
    executor.current_history_entry_id = ''
    executor.remote_execution_service = RemoteExecutionService(server)
    executor.use_foreground_guard = guard
    executor.foreground_source = 'cli'
    session.command_channel.wait_for_result = lambda *a, **kw: iter(())
    return executor, session, transport


@pytest.mark.parametrize('guard', [False, True])
@pytest.mark.parametrize('command', ['kill_instance', 'relaunch_instance', 'pwd'])
def test_command_dispatch_never_guesses_disconnect_reason(guard, command):
    executor, session, transport = _executor(guard)
    plan = {'command': command, 'command_type': 'command', 'extra': None}
    assert list(executor._execute_remote_plan(plan)()) == []
    assert transport.sent[0]['text'] == command
    assert session.context.server_disconnect_request is None
    assert session.get_foreground_task() is None


def test_failed_transport_send_does_not_guess_disconnect_reason():
    executor, session, transport = _executor(False)
    def raise_send(_):
        raise OSError('socket disconnected')
    transport.send = raise_send
    with pytest.raises(OSError, match='socket disconnected'):
        list(executor._execute_remote_plan({'command': 'kill_instance', 'command_type': 'command'})())
    assert session.context.server_disconnect_request is None


def test_explicit_web_disconnect_intent_is_unmodified():
    executor, session, transport = _executor(False)
    session.note_server_disconnect('disconnect')
    original = session.context.server_disconnect_request
    list(executor._execute_remote_plan({'command': 'kill_instance', 'command_type': 'command'})())
    assert session.context.server_disconnect_request is original
    assert original['command'] == 'disconnect'
