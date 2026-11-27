import base64
import secrets
import threading
import time
import uuid
from datetime import datetime

from core.protocol.message_types import (
    MSG_TYPE_PTY_CLOSE,
    MSG_TYPE_PTY_INPUT,
    MSG_TYPE_PTY_OPEN,
    MSG_TYPE_PTY_RESIZE,
)


class PtySessionService:
    TERMINAL_SESSION_RETENTION_SECONDS = 300

    def __init__(self, server, event_bus=None):
        self.server = server
        self.event_bus = event_bus
        self._lock = threading.RLock()
        self._sessions = {}
        self._cleanup_timers = {}
        self.max_chunks = 500

    def create_session(self, client_id: str, cols: int = 120, rows: int = 32, shell: str = '', cwd: str = '') -> dict:
        session = self.server.get_target_connection_by_client_id(client_id)
        pty_id = str(uuid.uuid4())
        now = time.time()
        item = {
            'pty_session_id': pty_id,
            'client_id': client_id,
            'status': 'opening',
            'created_at': now,
            'opened_at': 0,
            'closed_at': 0,
            'shell': shell or '',
            'backend': '',
            'cwd': cwd or '',
            'cols': max(20, int(cols or 120)),
            'rows': max(5, int(rows or 32)),
            'seq': 0,
            'chunks': [],
            'error': '',
            'exit_code': None,
            'open_notified': False,
            'close_notified': False,
            'ws_token': secrets.token_urlsafe(24),
        }
        with self._lock:
            self._sessions[pty_id] = item


        try:
            session.send({
                'type': MSG_TYPE_PTY_OPEN,
                'pty_session_id': pty_id,
                'shell': item['shell'],
                'cwd': item['cwd'],
                'cols': item['cols'],
                'rows': item['rows'],
            })
        except Exception as e:
            event_item = None
            with self._lock:
                item['status'] = 'error'
                item['error'] = str(e or 'PTY open failed')
                item['closed_at'] = time.time()
                if not item.get('close_notified'):
                    item['close_notified'] = True
                    event_item = dict(item)
            if event_item:
                self._publish_pty_lifecycle_event(event_item, state='error')
            self._schedule_terminal_session_cleanup(pty_id)
            raise

        with self._lock:
            return {
                'pty_session_id': pty_id,
                'status': item['status'],
                'backend': item['backend'],
                'cols': item['cols'],
                'rows': item['rows'],
                'ws_token': item['ws_token'],
            }

    def write_input(self, pty_session_id: str, data: str):
        item = self._get_required(pty_session_id)
        session = self.server.get_target_connection_by_client_id(item['client_id'])
        session.send({
            'type': MSG_TYPE_PTY_INPUT,
            'pty_session_id': pty_session_id,
            'data': data or '',
        })
        return {'ok': True}

    def resize_session(self, pty_session_id: str, cols: int, rows: int):
        item = self._get_required(pty_session_id)
        cols = max(20, int(cols or item['cols'] or 120))
        rows = max(5, int(rows or item['rows'] or 32))
        with self._lock:
            item['cols'] = cols
            item['rows'] = rows
        session = self.server.get_target_connection_by_client_id(item['client_id'])
        session.send({
            'type': MSG_TYPE_PTY_RESIZE,
            'pty_session_id': pty_session_id,
            'cols': cols,
            'rows': rows,
        })
        return {'ok': True}

    def close_session(self, pty_session_id: str, *, user_initiated=False, reason=''):
        item = self._get_required(pty_session_id)
        with self._lock:
            if item['status'] in ('closing', 'closed', 'error'):
                return {'ok': True}
            item['status'] = 'closing'
            client_id = item['client_id']

        session = self.server.get_target_connection_by_client_id(client_id)
        try:
            session.send({
                'type': MSG_TYPE_PTY_CLOSE,
                'pty_session_id': pty_session_id,
            })
        except Exception:
            # Client closure can still be observed through the existing session lifecycle.
            pass
        self._schedule_terminal_session_cleanup(pty_session_id)
        return {'ok': True}

    def get_updates(self, pty_session_id: str, after_seq: int = 0) -> dict:
        item = self._get_required(pty_session_id)
        with self._lock:
            chunks = [chunk for chunk in item['chunks'] if int(chunk.get('seq') or 0) > int(after_seq or 0)]
            return {
                'pty_session_id': pty_session_id,
                'status': item['status'],
                'seq': item['seq'],
                'chunks': chunks,
                'error': item.get('error') or '',
                'cols': item.get('cols') or 120,
                'rows': item.get('rows') or 32,
                'shell': item.get('shell') or '',
                'backend': item['backend'],
            }

    def handle_client_opened(self, pty_session_id: str, shell: str = '', backend: str = ''):
        event_item = None
        with self._lock:
            item = self._sessions.get(pty_session_id)
            if not item:
                return
            if item['status'] in ('closed', 'error'):
                return
            if item['status'] != 'closing':
                item['status'] = 'open'
            item['opened_at'] = time.time()
            if shell:
                item['shell'] = str(shell)
            if backend:
                item['backend'] = str(backend)

            if not item.get('open_notified'):
                item['open_notified'] = True
                event_item = dict(item)

        if event_item:
            self._publish_pty_lifecycle_event(event_item, state='opened')

    def handle_client_output(self, pty_session_id: str, data: str):
        text = ''
        try:
            raw = base64.b64decode(str(data or '').encode(), validate=False)
            text = raw.decode('utf-8', errors='replace')
        except Exception:
            text = str(data or '')
        with self._lock:
            item = self._sessions.get(pty_session_id)
            if not item:
                return
            item['seq'] += 1
            item['chunks'].append({'seq': item['seq'], 'text': text})
            if len(item['chunks']) > self.max_chunks:
                item['chunks'] = item['chunks'][-self.max_chunks:]

    def handle_client_closed(self, pty_session_id: str, exit_code=0):
        event_item = None
        with self._lock:
            item = self._sessions.get(pty_session_id)
            if not item:
                return
            item['status'] = 'closed'
            item['closed_at'] = time.time()
            item['exit_code'] = exit_code

            if item.get('open_notified') and not item.get('close_notified'):
                item['close_notified'] = True
                event_item = dict(item)

        if event_item:
            self._publish_pty_lifecycle_event(event_item, state='closed')
        self._schedule_terminal_session_cleanup(pty_session_id)

    def handle_client_error(self, pty_session_id: str, message: str):
        event_item = None
        with self._lock:
            item = self._sessions.get(pty_session_id)
            if not item:
                return
            item['status'] = 'error'
            item['error'] = str(message or 'PTY error')
            item['closed_at'] = time.time()
            item['seq'] += 1
            item['chunks'].append({
                'seq': item['seq'],
                'text': f"\r\n[PTY error] {item['error']}\r\n",
            })
            # item['chunks'].append({'seq': item['seq'], 'text': f"\n[PTY error] {item['error']}\n"})
            if len(item['chunks']) > self.max_chunks:
                item['chunks'] = item['chunks'][-self.max_chunks:]
            if not item.get('close_notified'):
                item['close_notified'] = True
                event_item = dict(item)

        if event_item:
            self._publish_pty_lifecycle_event(event_item, state='error')
        self._schedule_terminal_session_cleanup(pty_session_id)

    def handle_client_disconnected(self, client_id: str):
        client_id = str(client_id or '').strip()
        now = time.time()
        event_items = []
        session_ids = []

        with self._lock:
            for item in self._sessions.values():
                if item.get('client_id') != client_id:
                    continue
                if item.get('status') in ('closed', 'error'):
                    continue

                item['status'] = 'closed'
                item['closed_at'] = now
                item['error'] = 'Client disconnected'
                session_ids.append(item['pty_session_id'])

                if item.get('open_notified') and not item.get('close_notified'):
                    item['close_notified'] = True
                    event_items.append(dict(item))

        for event_item in event_items:
            self._publish_pty_lifecycle_event(event_item, state='closed')
        for pty_session_id in session_ids:
            self._schedule_terminal_session_cleanup(pty_session_id)

    def authorize_ws(self, pty_session_id: str, token: str) -> bool:
        with self._lock:
            item = self._sessions.get(str(pty_session_id))
            if not item:
                return False
            expected = str(item.get('ws_token') or '')
        return bool(expected) and bool(token) and secrets.compare_digest(expected, str(token))

    def _publish_pty_lifecycle_event(self, item: dict, state: str):
        if self.event_bus is None:
            return

        try:
            self.event_bus.publish('pty_lifecycle', {
                'client_id': item.get('client_id', ''),
                'pty_session_id': item.get('pty_session_id', ''),
                'state': state,
                'status': item.get('status', ''),
                'shell': item.get('shell', ''),
                'backend': item['backend'],
                'cwd': item.get('cwd', ''),
                'exit_code': item.get('exit_code'),
                'error': item.get('error', ''),
                'time': datetime.now().isoformat(),
            })
        except Exception:
            pass

    def _schedule_terminal_session_cleanup(self, pty_session_id: str):
        session_id = str(pty_session_id)

        def cleanup():
            with self._lock:
                if self._cleanup_timers.get(session_id) is not timer:
                    return
                self._cleanup_timers.pop(session_id, None)

                item = self._sessions.get(session_id)
                if not item:
                    return
                if item.get('status') not in ('closing', 'closed', 'error'):
                    return
                self._sessions.pop(session_id, None)

        with self._lock:
            existing_timer = self._cleanup_timers.get(session_id)
            if existing_timer is not None and existing_timer.is_alive():
                return

            timer = threading.Timer(self.TERMINAL_SESSION_RETENTION_SECONDS, cleanup)
            timer.daemon = True
            self._cleanup_timers[session_id] = timer

        try:
            timer.start()
        except Exception:
            with self._lock:
                if self._cleanup_timers.get(session_id) is timer:
                    self._cleanup_timers.pop(session_id, None)
            raise

    def get_ws_info(self, pty_session_id: str) -> dict:
        with self._lock:
            item = self._get_required(pty_session_id)
            return {'pty_session_id': item['pty_session_id'], 'ws_token': item.get('ws_token') or ''}

    def _get_required(self, pty_session_id: str) -> dict:
        with self._lock:
            item = self._sessions.get(str(pty_session_id))
            if item is not None:
                return item
        raise KeyError('PTY session not found')
