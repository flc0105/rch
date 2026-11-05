import asyncio
import os
import json
from typing import Optional

from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from server.config.config import WEB_PORT, WEB_WS_PORT
from server.web.auth_guard import WebAuthGuard

class WebSocketAdapter:
    """Transport wrapper for the existing PTY/Screen WS handlers."""
    def __init__(self, connection):
        self.connection = connection
        self.query_params = {key: values[-1] for key, values in parse_qs(urlsplit(connection.request.path).query).items()}

    async def accept(self):
        return None

    async def close(self, code=1000):
        await self.connection.close(code=code)

    async def send_text(self, text):
        await self.connection.send(text)

    async def receive_text(self):
        return await self.connection.recv()


from core.protocol.screen import SCREEN_DEFAULT_FPS


def create_ws_handler(server_instance, flask_app):
    async def pty_ws(websocket, pty_session_id: str):
        token = str(websocket.query_params.get('token') or '')
        terminal_api = server_instance.web_service.terminal_api
        pty_service = terminal_api.pty_session_service

        if not pty_service.authorize_ws(pty_session_id, token):
            await websocket.close(code=4403)
            return

        await websocket.accept()

        sender_task: Optional[asyncio.Task] = None
        receiver_task: Optional[asyncio.Task] = None
        closed_sent = False

        async def sender_loop():
            nonlocal closed_sent
            after_seq = 0
            last_status = None
            while True:
                payload = pty_service.get_updates(pty_session_id, after_seq=after_seq)
                chunks = payload.get('chunks') or []
                status = payload.get('status') or ''
                error = payload.get('error') or ''
                shell = payload.get('shell') or ''
                seq = int(payload.get('seq') or after_seq or 0)
                if seq > after_seq:
                    after_seq = seq

                status_changed = status != last_status

                # 有输出时把状态一起带上，确保 error 文本先写入终端再关闭 socket。
                if chunks:
                    await websocket.send_text(json.dumps({
                        'type': 'output',
                        'chunks': chunks,
                        'status': status,
                        'error': error,
                        'shell': shell,
                        'seq': seq,
                    }, ensure_ascii=False))
                elif status_changed:
                    await websocket.send_text(json.dumps({
                        'type': 'status',
                        'status': status,
                        'error': error,
                        'shell': shell,
                        'seq': seq,
                    }, ensure_ascii=False))

                last_status = status

                if status in ('closed', 'error'):
                    closed_sent = True
                    break

                await asyncio.sleep(0.05)

        async def receiver_loop():
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw or '{}')
                except Exception:
                    continue

                msg_type = str(message.get('type') or '').strip().lower()
                if msg_type == 'input':
                    terminal_api.send_pty_input(pty_session_id, str(message.get('data') or ''))
                elif msg_type == 'resize':
                    terminal_api.resize_pty_session(
                        pty_session_id,
                        cols=message.get('cols') or 120,
                        rows=message.get('rows') or 32,
                    )
                elif msg_type == 'close':
                    terminal_api.close_pty_session(pty_session_id)
                    break

        try:
            sender_task = asyncio.create_task(sender_loop())
            receiver_task = asyncio.create_task(receiver_loop())
            done, pending = await asyncio.wait(
                [sender_task, receiver_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
        except ConnectionClosed:
            try:
                terminal_api.close_pty_session(pty_session_id)
            except Exception:
                pass
        except Exception:
            try:
                terminal_api.close_pty_session(pty_session_id)
            except Exception:
                pass
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
        finally:
            for task in (sender_task, receiver_task):
                if task and not task.done():
                    task.cancel()
            try:
                terminal_api.close_pty_session(pty_session_id)
            except Exception:
                pass


    async def screen_ws(websocket, screen_session_id: str):
        token = str(websocket.query_params.get('token') or '')
        screen_view_api = server_instance.web_service.screen_view_api
        screen_service = screen_view_api.screen_view_session_service

        if not screen_service.authorize_ws(screen_session_id, token):
            await websocket.close(code=4403)
            return

        await websocket.accept()

        sender_task: Optional[asyncio.Task] = None
        receiver_task: Optional[asyncio.Task] = None
        closed_sent = False

        async def sender_loop():
            nonlocal closed_sent
            after_seq = 0
            while True:
                payload = screen_service.get_updates(screen_session_id, after_seq=after_seq)
                status = payload.get('status') or ''
                error = payload.get('error') or ''
                seq = int(payload.get('seq') or after_seq or 0)
                frames = payload.get('frames') if isinstance(payload.get('frames'), list) else []

                if seq > after_seq and frames:
                    after_seq = seq
                    await websocket.send_text(json.dumps({
                        'type': 'frames',
                        'status': status,
                        'error': error,
                        'seq': seq,
                        'frames': frames,
                        'frame_strategy': payload.get('frame_strategy') or '',
                        'width': payload.get('width') or 0,
                        'height': payload.get('height') or 0,
                        'frame_bytes': payload.get('frame_bytes') or 0,
                        'captured_at': payload.get('captured_at') or 0,
                        'fps': payload.get('fps') or SCREEN_DEFAULT_FPS,
                        'quality': payload.get('quality') or 60,
                        'control_enabled': bool(payload.get('control_enabled')),
                        'control_error': payload.get('control_error') or '',
                    }, ensure_ascii=False))

                if status in ('closed', 'error'):
                    if not closed_sent:
                        await websocket.send_text(json.dumps({
                            'type': 'status',
                            'status': status,
                            'error': error,
                            'seq': seq,
                            'frame_strategy': payload.get('frame_strategy') or '',
                            'control_enabled': bool(payload.get('control_enabled')),
                            'control_error': payload.get('control_error') or '',
                        }, ensure_ascii=False))
                        closed_sent = True
                    break

                await asyncio.sleep(0.03)

        async def receiver_loop():
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw or '{}')
                except Exception:
                    continue

                msg_type = str(message.get('type') or '').strip().lower()
                if msg_type == 'config':
                    screen_view_api.update_screen_view(
                        screen_session_id,
                        fps=message.get('fps'),
                        quality=message.get('quality'),
                    )
                elif msg_type == 'control':
                    screen_view_api.set_screen_control(
                        screen_session_id,
                        bool(message.get('enabled')),
                    )
                elif msg_type == 'input':
                    screen_view_api.send_screen_input(
                        screen_session_id,
                        message.get('event') if isinstance(message.get('event'), dict) else {},
                    )
                elif msg_type == 'close':
                    screen_view_api.close_screen_view(screen_session_id)
                    break

        try:
            sender_task = asyncio.create_task(sender_loop())
            receiver_task = asyncio.create_task(receiver_loop())
            done, pending = await asyncio.wait(
                [sender_task, receiver_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
        except ConnectionClosed:
            try:
                screen_view_api.close_screen_view(screen_session_id)
            except Exception:
                pass
        except Exception:
            try:
                screen_view_api.close_screen_view(screen_session_id)
            except Exception:
                pass
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
        finally:
            for task in (sender_task, receiver_task):
                if task and not task.done():
                    task.cancel()
            try:
                screen_view_api.close_screen_view(screen_session_id)
            except Exception:
                pass

    def authorized(connection, *, require_origin=True):
        headers = connection.request.headers
        origin = headers.get('Origin', '')
        # Browser connections may only originate from RCH's HTTP Web UI.
        if origin:
            url = urlsplit(origin)
            request_host = urlsplit('http://' + headers.get('Host', ''))
            same_host = (url.hostname or '').lower() == (request_host.hostname or '').lower()
            dev_port = int(os.environ.get('RCH_VITE_PORT', '5173'))
            # Vite forwards /ws with the original Host header; require the
            # browser origin and forwarded Host to match that configured port.
            dev_proxy = same_host and url.port == dev_port and request_host.port == dev_port
            if (not same_host) or (url.port not in (WEB_PORT, None) and not dev_proxy) or url.scheme not in ('http', 'https'):
                return False
        elif require_origin:
            # Non-browser notification clients may authenticate with a Bearer token.
            if not headers.get('Authorization', ''):
                return False
        # Browsers use their session cookie; external consumers use an Authorization header.
        with flask_app.test_request_context('/api/stream', headers={
            'Cookie': headers.get('Cookie', ''),
            'Authorization': headers.get('Authorization', ''),
        }):
            guard = WebAuthGuard(client_session_token_service=getattr(server_instance.web_service, 'client_session_token_service', None))
            return guard.has_valid_static_token() or guard.has_valid_session()

    async def stream_events(connection, tab_id):
        bus = server_instance.web_service.event_bus
        q = bus.subscribe_async(tab_id=tab_id)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    item = {'event': 'ping', 'data': {'time': datetime.now().isoformat()}, 'id': ''}
                if item is None:
                    await connection.close(code=1013, reason='Event backlog exceeded')
                    return
                await connection.send(json.dumps(item, ensure_ascii=False))
        finally:
            bus.unsubscribe(q)

    async def stream_notifications(connection, last_event_id):
        service = server_instance.web_service
        bus = service.event_bus
        q = bus.subscribe_async(event_types={'notification_center_updated'})
        try:
            seen = set()
            async def send_notification(notification, notification_id):
                key = str(notification.get('notification_key') or '').strip()
                if service.notification_preferences_api.is_delivery_enabled(key):
                    event = 'notification'; data = notification
                else:
                    event = 'cursor'
                    data = {'notification_id': notification_id, 'notification_key': key, 'reason': 'disabled_by_preference'}
                await connection.send(json.dumps({'id': notification_id, 'event': event, 'data': data}, ensure_ascii=False))

            if last_event_id:
                replay = service.notification_history_api.get_notifications_after(last_event_id)
                if not replay.get('cursor_found'):
                    await connection.send(json.dumps({'event': 'reset', 'data': {'reason': 'cursor_not_found', 'last_event_id': last_event_id}}))
                else:
                    for notification in replay.get('notifications') or []:
                        event_id = str(notification.get('id') or '').strip()
                        if event_id:
                            seen.add(event_id)
                            await send_notification(notification, event_id)
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    await connection.send(json.dumps({'event': 'ping', 'data': {'time': datetime.now().isoformat()}}))
                    continue
                if item is None:
                    await connection.close(code=1013, reason='Event backlog exceeded')
                    return
                data = item.get('data') or {}
                if data.get('action') != 'added' or not isinstance(data.get('notification'), dict):
                    continue
                notification = data['notification']
                event_id = str(notification.get('id') or '').strip()
                if not event_id:
                    continue
                if event_id in seen:
                    seen.discard(event_id)
                    continue
                await send_notification(notification, event_id)
        finally:
            bus.unsubscribe(q)

    async def dispatch(connection):
        # Signed PTY/Screen tickets remain bound to their session, while the
        # shared event stream requires the authenticated Web session.
        path = urlsplit(connection.request.path).path
        if path.startswith('/ws/pty/'):
            await pty_ws(WebSocketAdapter(connection), path.removeprefix('/ws/pty/'))
        elif path.startswith('/ws/screen/'):
            await screen_ws(WebSocketAdapter(connection), path.removeprefix('/ws/screen/'))
        elif path == '/ws/events':
            if not authorized(connection):
                await connection.close(code=4403)
                return
            params = parse_qs(urlsplit(connection.request.path).query)
            await stream_events(connection, params.get('tab_id', [''])[-1])
        elif path == '/ws/notifications':
            if not authorized(connection):
                await connection.close(code=4403)
                return
            params = parse_qs(urlsplit(connection.request.path).query)
            await stream_notifications(connection, params.get('last_event_id', [''])[-1])
        else:
            await connection.close(code=4404)

    return dispatch


async def run_ws_server(server_instance, flask_app, ready=None):
    handler = create_ws_handler(server_instance, flask_app)
    async with serve(handler, '0.0.0.0', WEB_WS_PORT, max_size=16 * 1024 * 1024):
        if ready is not None:
            ready.set()
        await asyncio.Future()

