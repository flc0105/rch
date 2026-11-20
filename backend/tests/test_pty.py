"""Windows PTY backend selection and reporting, with native calls stubbed."""

import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.pty.backends import windows_pty_backend, windows_pty_worker
from client.pty.manager import PtyManager
from server.application.preferences.notification_event_projector import NotificationEventProjector
from server.application.terminal.pty_session_service import PtySessionService
from server.connection.services.message_router import ServerInboundMessageRouter


@pytest.mark.parametrize('build, selector, name', [
    (14393, 1, 'WinPTY'),
    (17762, 1, 'WinPTY'),
    (17763, 0, 'ConPTY'),
])
def test_windows_pty_reports_the_spawned_backend(monkeypatch, build, selector, name):
    pty = Mock(pid=123)
    pty.spawn.return_value = True
    create_pty = Mock(return_value=pty)
    monkeypatch.setitem(sys.modules, 'winpty', SimpleNamespace(
        Backend=SimpleNamespace(ConPTY=0), PTY=create_pty,
    ))
    monkeypatch.setattr(windows_pty_worker.metadata, 'version', lambda _: '3.0.5')
    monkeypatch.setattr(sys, 'getwindowsversion', lambda: SimpleNamespace(
        platform_version=(10, 0, build),
    ), raising=False)
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(
        b'{"op":"open","cols":80,"rows":24,"application":"cmd.exe","command":"cmd.exe"}\n'
        b'{"op":"close"}\n',
    )))
    monkeypatch.setattr(windows_pty_worker.ctypes, 'WinDLL', lambda *args, **kwargs: SimpleNamespace(
        SetConsoleCtrlHandler=Mock(return_value=True),
    ), raising=False)
    messages = []
    monkeypatch.setattr(windows_pty_worker, '_send', lambda event, **fields: messages.append({'event': event, **fields}))
    monkeypatch.setattr(windows_pty_worker, '_read_output', Mock())
    monkeypatch.setattr(windows_pty_worker, '_stop_pty', Mock())

    windows_pty_worker.run()

    create_pty.assert_called_once_with(80, 24, backend=selector)
    assert messages[0] == {'event': 'stage', 'value': f'{name} initialization'}
    assert messages[-1] == {'event': 'opened', 'pid': 123, 'backend': name}

    event_bus = Mock()
    connection = SimpleNamespace(send=Mock())
    service = PtySessionService(SimpleNamespace(get_target_connection_by_client_id=lambda _: connection), event_bus)
    opened = service.create_session('win')
    assert (opened['status'], opened['backend']) == ('opening', '')
    session_id = opened['pty_session_id']
    router = ServerInboundMessageRouter(SimpleNamespace(context=SimpleNamespace(on_pty_opened=service.handle_client_opened)))
    manager = PtyManager(SimpleNamespace(send=router.dispatch))
    backend = manager.windows_backend
    process = SimpleNamespace(stdout=io.BytesIO(b'\n'.join(json.dumps(message).encode('ascii') for message in messages)))
    monkeypatch.setattr(windows_pty_backend, '_Worker', lambda proc: SimpleNamespace(process=proc, send=Mock(return_value=True)))
    monkeypatch.setattr(backend, '_launch', lambda: process)
    monkeypatch.setattr(backend, 'build_windows_command', lambda _: ('cmd.exe', 'cmd.exe'))
    monkeypatch.setattr(backend, 'reader_loop', Mock())
    token = object()
    manager._windows_opening[session_id] = (token, Mock(), 'helper startup')

    assert backend.open_session(session_id, opening=token) is True

    status = service.get_updates(session_id)
    assert (status['status'], status['backend']) == ('open', name)
    topic, lifecycle = event_bus.publish.call_args.args
    assert (topic, lifecycle['backend']) == ('pty_lifecycle', name)
    projector = NotificationEventProjector(history_store=None, server=None)
    monkeypatch.setattr(projector, '_device_name', lambda _: 'Windows')
    assert projector._build_pty_lifecycle(lifecycle)['message'] == f'PTY ({name}) session started on Windows'
