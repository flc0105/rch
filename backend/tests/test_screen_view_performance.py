"""Regression coverage for self-contained deltas and push-based screen updates."""
import asyncio
import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from client.screen.frame_strategies.keyframe_delta import KeyframeDeltaFrameStrategy
from server.application.screen.screen_view_session_service import ScreenViewSessionService
from server.application.web.screen_view_api import WebScreenViewApi


def test_static_delta_is_not_encoded_again_and_return_to_base_is_explicit():
    strategy = KeyframeDeltaFrameStrategy()
    a = Image.new('RGB', (200, 200), 'black')
    b = a.copy()
    ImageDraw.Draw(b).rectangle((30, 30, 55, 55), fill='white')
    key = strategy.encode(a, 60)
    delta = strategy.encode(b, 60)
    assert key['frame_type'] == 'keyframe'
    assert delta['frame_type'] == 'delta' and delta['base_seq'] == key['frame_seq']
    assert strategy.encode(b.copy(), 60) is None
    c = b.copy()
    ImageDraw.Draw(c).rectangle((31, 31, 54, 54), fill="red")
    changed = strategy.encode(c, 60)
    assert changed["frame_type"] == "delta" and changed["base_seq"] == key["frame_seq"]
    assert strategy.encode(c, 60) is None
    restore = strategy.encode(a, 60)
    assert restore['frame_type'] == 'keyframe' and restore['frame_seq'] == changed['frame_seq'] + 1
    assert strategy.encode(a, 60) is None
    assert strategy.encode(a, 75)['frame_type'] == 'keyframe'


def test_moving_patch_keeps_original_keyframe_dependency():
    strategy = KeyframeDeltaFrameStrategy()
    a = Image.new('RGB', (200, 200), 'black')
    base = strategy.encode(a, 60)
    for x in (20, 60, 100):
        b = a.copy()
        ImageDraw.Draw(b).rectangle((x, 20, x + 5, 25), fill='white')
        delta = strategy.encode(b, 60)
        assert delta['base_seq'] == base['frame_seq'] and delta['frame_type'] == 'delta'
        assert delta['patch_x'] <= x < delta['patch_x'] + delta['patch_width']
    strategy._base_created_at -= 3
    assert strategy.encode(b, 60)['frame_type'] == 'keyframe'
    assert strategy.encode(Image.new('RGB', (300, 300)), 60)['frame_type'] == 'keyframe'


def make_service(send=None):
    connection = SimpleNamespace(send=send or Mock())
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _: connection)
    service = ScreenViewSessionService(server)
    info = service.create_session('client')
    return service, info


def frame(service, sid, seq=1, kind='keyframe', base=1):
    service.handle_client_frame(sid, 'jpeg', 100, 100, 4, 10, 'keyframe_delta', kind, seq, base, 0, 0, 10, 10,
                                {'capture_fps': 24.5})


def test_updates_include_frame_stats_and_independent_status_notifications():
    service, info = make_service()
    sid = info['screen_session_id']
    callback = Mock()
    service.subscribe_updates(sid, callback)
    service.handle_client_opened(sid, frame_strategy='keyframe_delta')
    frame(service, sid)
    frame(service, sid, 2, 'delta')
    assert [f['seq'] for f in service.get_updates(sid)['frames']] == [1, 2]
    assert service.get_updates(sid)['performance'] == {'capture_fps': 24.5}
    service.handle_client_input_error(sid, 'UAC')
    assert service.get_updates(sid, 2)['frames'] == []
    assert service.get_updates(sid, 2)['control_error'] == 'UAC'
    service.handle_client_disconnected('client')
    assert service.get_updates(sid, 2)['status'] == 'closed'
    assert callback.call_count == 5
    service.unsubscribe_updates(sid, callback)
    service.handle_client_closed(sid)
    assert callback.call_count == 5
    assert not service._update_listeners


def load_ws_handler():
    # Isolate unrelated HTTP auth/config imports; exercise actual WS dispatch,
    # ScreenViewSessionService and WebScreenViewApi, without binding a port.
    config = ModuleType('server.config.config')
    config.WEB_PORT = 8085
    config.WEB_WS_PORT = 8086
    auth = ModuleType('server.web.auth_guard')
    auth.WebAuthGuard = object
    path = Path(__file__).resolve().parents[1] / 'server/web/ws_server.py'
    spec = importlib.util.spec_from_file_location('screen_ws_under_test', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'server.config.config': config, 'server.web.auth_guard': auth}):
        spec.loader.exec_module(module)
    return module.create_ws_handler


def test_ws_push_status_without_frame_and_input_does_not_block_event_loop():
    async def run():
        entered, release = threading.Event(), threading.Event()
        def send(message):
            if message.get('event', {}).get('action') == 'mouse_move':
                entered.set()
                assert release.wait(2)
        service, info = make_service(send)
        sid = info['screen_session_id']
        service.handle_client_opened(sid, frame_strategy='keyframe_delta')
        incoming, outgoing = asyncio.Queue(), asyncio.Queue()
        class Socket:
            request = SimpleNamespace(path=f'/ws/screen/{sid}?token={info["ws_token"]}')
            async def recv(self):
                return await incoming.get()
            async def send(self, text):
                await outgoing.put(json.loads(text))
            async def close(self, code=1000):
                pass
        api = WebScreenViewApi(service)
        handler = load_ws_handler()(SimpleNamespace(web_service=SimpleNamespace(screen_view_api=api)), None)
        task = asyncio.create_task(handler(Socket()))
        try:
            first = await asyncio.wait_for(outgoing.get(), 1)
            assert first['type'] == 'status' and first['status'] == 'open'
            await incoming.put(json.dumps({'type': 'input', 'event': {'action': 'mouse_move', 'x': 0.2, 'y': 0.3}}))
            assert await asyncio.to_thread(entered.wait, 1)
            await asyncio.to_thread(frame, service, sid)
            result = await asyncio.wait_for(outgoing.get(), 0.5)
            assert result['type'] == 'frames' and result['performance']['capture_fps'] == 24.5
            await asyncio.to_thread(service.handle_client_input_error, sid, 'UAC')
            result = await asyncio.wait_for(outgoing.get(), 0.5)
            assert result['type'] == 'status' and result['control_error'] == 'UAC'
            release.set()
            await asyncio.to_thread(service.handle_client_disconnected, 'client')
            result = await asyncio.wait_for(outgoing.get(), 0.5)
            assert result['status'] == 'closed'
            await asyncio.wait_for(task, 1)
            assert not service._update_listeners
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_client_reports_actual_sampling_statistics(monkeypatch):
    from client.screen.manager import ScreenViewManager
    from client.screen.frame_strategies.full_jpeg import FullJpegFrameStrategy
    monkeypatch.setattr('client.screen.manager.get_local_identity', lambda: SimpleNamespace(os_alias='linux'))
    monkeypatch.setattr('client.screen.manager.build_screen_frame_strategy', FullJpegFrameStrategy)
    reported = threading.Event()
    frames = []
    def send(message):
        if message.get('type') == 'screen_frame':
            frames.append(message)
            if message.get('performance'):
                reported.set()
    manager = ScreenViewManager(SimpleNamespace(send=send))
    monkeypatch.setattr(manager, '_capture_image', lambda: Image.new('RGB', (24, 24)))
    monkeypatch.setattr(manager, '_apply_input_event', lambda *_: None)
    monkeypatch.setattr(manager, '_release_session_inputs', lambda *_, **__: None)
    manager.open_session('perf', fps=30)
    with manager._lock:
        item = manager._sessions['perf']
    try:
        manager.handle_input('perf', {'action': 'mouse_move', 'x': 0.5})
        assert reported.wait(3)
        stats = frames[-1]['performance']
        assert 0 < stats['capture_fps'] <= 32
        assert stats['send_fps'] == stats['capture_fps']
        assert all(stats[name] >= 0 for name in ('capture_ms', 'encode_ms', 'send_ms', 'input_queue_ms'))
        assert frames[-1]['captured_at'] > 0
    finally:
        manager.close_session('perf')
        item['thread'].join(2)
        item['input_worker'].join(2)
