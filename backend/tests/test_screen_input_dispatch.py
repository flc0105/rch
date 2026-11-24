"""Screen input is asynchronous, ordered and safely released on shutdown."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.screen.manager import ScreenViewManager


def _manager(monkeypatch):
    monkeypatch.setattr('client.screen.manager.get_local_identity',
                        lambda: SimpleNamespace(os_alias='linux'))
    manager = ScreenViewManager(SimpleNamespace(send=Mock()))
    monkeypatch.setattr(manager, '_capture_image', Mock(return_value=SimpleNamespace(
        width=2, height=2,
    )))
    # Avoid OS frame capture while exercising the input worker.
    monkeypatch.setattr(manager, '_capture_loop', lambda session_id: manager._sessions[session_id]['stop_event'].wait())
    return manager


def _wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_initial_input_preparation_does_not_block_socket_receive_thread(monkeypatch):
    manager = _manager(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    processed = []

    def apply(_item, action, payload):
        entered.set()
        if action == 'prepare':
            assert release.wait(2)
        processed.append((action, payload))

    monkeypatch.setattr(manager, '_apply_input_event', apply)
    monkeypatch.setattr(manager, '_release_session_inputs', Mock())
    assert manager.open_session('screen')
    try:
        assert manager.handle_input('screen', {'action': 'prepare'})
        assert entered.wait(1)
        start = time.monotonic()
        assert manager.handle_input('screen', {'action': 'key_down', 'key': 'a'})
        assert time.monotonic() - start < 0.1
        release.set()
        assert _wait_until(lambda: len(processed) == 2)
        assert [action for action, _ in processed] == ['prepare', 'key_down']
    finally:
        release.set()
        manager.close_session('screen')
        manager._sessions['screen']['input_worker'].join(2)


def test_mouse_moves_coalesce_without_dropping_button_order(monkeypatch):
    manager = _manager(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    processed = []

    def apply(_item, action, payload):
        if action == 'prepare':
            entered.set()
            assert release.wait(2)
        processed.append((action, payload))

    monkeypatch.setattr(manager, '_apply_input_event', apply)
    monkeypatch.setattr(manager, '_release_session_inputs', Mock())
    manager.open_session('screen')
    try:
        manager.handle_input('screen', {'action': 'prepare'})
        assert entered.wait(1)
        for value in range(50):
            manager.handle_input('screen', {'action': 'mouse_move', 'x': value})
        manager.handle_input('screen', {'action': 'mouse_down', 'button': 'left'})
        manager.handle_input('screen', {'action': 'mouse_move', 'x': 75})
        manager.handle_input('screen', {'action': 'mouse_up', 'button': 'left'})
        release.set()
        assert _wait_until(lambda: len(processed) == 5)
        assert [action for action, _ in processed] == [
            'prepare', 'mouse_move', 'mouse_down', 'mouse_move', 'mouse_up'
        ]
        assert processed[1][1]['x'] == 49
        assert processed[3][1]['x'] == 75
    finally:
        release.set()
        item = manager._sessions['screen']
        manager.close_session('screen')
        item['input_worker'].join(2)


def test_release_all_discards_pending_input_and_shutdown_releases_keys(monkeypatch):
    manager = _manager(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    processed = []
    releases = Mock()

    def apply(_item, action, payload):
        if action == 'prepare':
            entered.set()
            assert release.wait(2)
        processed.append(action)

    monkeypatch.setattr(manager, '_apply_input_event', apply)
    monkeypatch.setattr(manager, '_release_session_inputs', releases)
    manager.open_session('screen')
    item = manager._sessions['screen']
    try:
        manager.handle_input('screen', {'action': 'prepare'})
        assert entered.wait(1)
        manager.handle_input('screen', {'action': 'key_down', 'key': 'ctrl'})
        manager.handle_input('screen', {'action': 'mouse_move', 'x': 0.5})
        manager.handle_input('screen', {'action': 'release_all'})
        release.set()
        assert _wait_until(lambda: processed == ['prepare', 'release_all'])
    finally:
        release.set()
        manager.close_session('screen')
        item['input_worker'].join(2)
    assert not item['input_worker'].is_alive()
    releases.assert_any_call(item, restore_control=True)
    assert not manager.handle_input('screen', {'action': 'mouse_move', 'x': 0.2})


def test_critical_input_queue_overflow_reports_error_and_schedules_release(monkeypatch):
    manager = _manager(monkeypatch)
    manager.MAX_PENDING_INPUT_EVENTS = 2
    entered = threading.Event()
    release = threading.Event()
    actions = []

    def apply(_item, action, _payload):
        if action == 'prepare':
            entered.set()
            assert release.wait(2)
        actions.append(action)

    monkeypatch.setattr(manager, '_apply_input_event', apply)
    monkeypatch.setattr(manager, '_release_session_inputs', Mock())
    manager.open_session('screen')
    item = manager._sessions['screen']
    try:
        manager.handle_input('screen', {'action': 'prepare'})
        assert entered.wait(1)
        assert manager.handle_input('screen', {'action': 'key_down', 'key': 'a'})
        assert manager.handle_input('screen', {'action': 'key_up', 'key': 'a'})
        assert not manager.handle_input('screen', {'action': 'key_down', 'key': 'b'})
        release.set()
        assert _wait_until(lambda: actions == ['prepare', 'release_all'])
        sent = [call.args[0] for call in manager.connection.send.call_args_list]
        assert any(message.get('type') == 'screen_input_error' for message in sent)
    finally:
        release.set()
        manager.close_session('screen')
        item['input_worker'].join(2)


def test_input_failure_reports_error_and_worker_remains_usable(monkeypatch):
    manager = _manager(monkeypatch)
    applied = []
    released = Mock()

    def apply(_item, action, _payload):
        applied.append(action)
        if action == 'key_down':
            raise RuntimeError('OS input permission denied')

    monkeypatch.setattr(manager, '_apply_input_event', apply)
    monkeypatch.setattr(manager, '_release_session_inputs', released)
    manager.open_session('screen')
    item = manager._sessions['screen']
    try:
        assert manager.handle_input('screen', {'action': 'key_down', 'key': 'a'})
        assert _wait_until(lambda: any(
            msg.get('type') == 'screen_input_error'
            for msg in (call.args[0] for call in manager.connection.send.call_args_list)
        ))
        assert manager.handle_input('screen', {'action': 'control_off'})
        assert _wait_until(lambda: 'control_off' in applied)
        released.assert_called()
    finally:
        manager.close_session('screen')
        item['input_worker'].join(2)


def test_windows_prepare_waits_for_first_frame_without_blocking_receiver(monkeypatch):
    """Cold Windows input imports cannot contend with the first screenshot."""
    monkeypatch.setattr('client.screen.manager.get_local_identity',
                        lambda: SimpleNamespace(os_alias='win'))
    preloaded = threading.Event()
    monkeypatch.setattr(ScreenViewManager, '_preload_windows_screen_modules',
                        staticmethod(preloaded.set))
    manager = ScreenViewManager(SimpleNamespace(send=Mock()))
    assert preloaded.wait(1)
    monkeypatch.setattr(manager, '_capture_loop',
                        lambda session_id: manager._sessions[session_id]['stop_event'].wait())
    actions = []
    monkeypatch.setattr(manager, '_apply_input_event',
                        lambda _item, action, _payload: actions.append(action))
    monkeypatch.setattr(manager, '_release_session_inputs', Mock())

    assert manager.open_session('win-screen')
    item = manager._sessions['win-screen']
    try:
        assert manager.handle_input('win-screen', {'action': 'prepare'})
        assert manager.handle_input('win-screen', {'action': 'mouse_move', 'x': 0.5, 'y': 0.5})
        time.sleep(0.07)
        assert actions == []
        item['first_frame_sent'].set()
        assert _wait_until(lambda: actions == ['prepare', 'mouse_move'])
    finally:
        manager.close_session('win-screen')
        item['input_worker'].join(2)


def test_windows_first_frame_wait_is_interrupted_by_close(monkeypatch):
    monkeypatch.setattr('client.screen.manager.get_local_identity',
                        lambda: SimpleNamespace(os_alias='win'))
    monkeypatch.setattr(ScreenViewManager, '_preload_windows_screen_modules',
                        staticmethod(lambda: None))
    manager = ScreenViewManager(SimpleNamespace(send=Mock()))
    monkeypatch.setattr(manager, '_capture_loop',
                        lambda session_id: manager._sessions[session_id]['stop_event'].wait())
    apply = Mock()
    monkeypatch.setattr(manager, '_apply_input_event', apply)
    monkeypatch.setattr(manager, '_release_session_inputs', Mock())

    manager.open_session('win-screen')
    item = manager._sessions['win-screen']
    manager.handle_input('win-screen', {'action': 'prepare'})
    time.sleep(0.07)
    manager.close_session('win-screen')
    item['input_worker'].join(2)
    assert not item['input_worker'].is_alive()
    apply.assert_not_called()
