import asyncio
import json
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.wsgi import WSGIMiddleware

from core.protocol.screen import SCREEN_DEFAULT_FPS
from server.web.app import create_app


def create_asgi_app(server_instance):
    flask_app = create_app(server_instance)
    app = FastAPI()

    @app.websocket("/ws/pty/{pty_session_id}")
    async def pty_ws(websocket: WebSocket, pty_session_id: str):
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
                except Exception:
                    pass
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
        except WebSocketDisconnect:
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


    @app.websocket("/ws/screen/{screen_session_id}")
    async def screen_ws(websocket: WebSocket, screen_session_id: str):
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
                except Exception:
                    pass
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
        except WebSocketDisconnect:
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

    app.mount('/', WSGIMiddleware(flask_app))
    return app
