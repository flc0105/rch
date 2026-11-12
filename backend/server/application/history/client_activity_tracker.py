"""Correlate dispatched UI operations with Client acknowledgements and session end."""
import logging
import threading
from datetime import datetime

from core.protocol.message_types import (
    MSG_TYPE_PTY_OPEN, MSG_TYPE_PTY_CLOSE, MSG_TYPE_PTY_OPENED, MSG_TYPE_PTY_CLOSED, MSG_TYPE_PTY_ERROR,
    MSG_TYPE_SCREEN_OPEN, MSG_TYPE_SCREEN_CLOSE, MSG_TYPE_SCREEN_OPENED, MSG_TYPE_SCREEN_CLOSED, MSG_TYPE_SCREEN_ERROR,
    MSG_TYPE_CLIPBOARD_SET, MSG_TYPE_CLIPBOARD_RESULT,
)
from server.application.history.activity_definitions import (
    ActivityAction, ActivityKind, clipboard_arguments,
)


class ClientActivityTracker:
    """The only lifecycle owner for PTY, Screen and Clipboard Activities."""

    _OPEN = {
        MSG_TYPE_PTY_OPEN: (ActivityKind.PTY, 'pty_session_id'),
        MSG_TYPE_SCREEN_OPEN: (ActivityKind.SCREEN_VIEW, 'screen_session_id'),
        MSG_TYPE_CLIPBOARD_SET: (ActivityKind.CLIPBOARD, 'clipboard_request_id'),
    }
    _CLOSE = {
        MSG_TYPE_PTY_CLOSE: (ActivityKind.PTY, 'pty_session_id'),
        MSG_TYPE_SCREEN_CLOSE: (ActivityKind.SCREEN_VIEW, 'screen_session_id'),
    }
    _RESULT = {
        MSG_TYPE_PTY_OPENED: (ActivityKind.PTY, 'pty_session_id'),
        MSG_TYPE_PTY_CLOSED: (ActivityKind.PTY, 'pty_session_id'),
        MSG_TYPE_PTY_ERROR: (ActivityKind.PTY, 'pty_session_id'),
        MSG_TYPE_SCREEN_OPENED: (ActivityKind.SCREEN_VIEW, 'screen_session_id'),
        MSG_TYPE_SCREEN_CLOSED: (ActivityKind.SCREEN_VIEW, 'screen_session_id'),
        MSG_TYPE_SCREEN_ERROR: (ActivityKind.SCREEN_VIEW, 'screen_session_id'),
        MSG_TYPE_CLIPBOARD_RESULT: (ActivityKind.CLIPBOARD, 'clipboard_request_id'),
    }

    def __init__(self, history):
        self.history = history
        self._lock = threading.RLock()
        self._active = {}

    @staticmethod
    def _key(conn, kind, identifier):
        return id(conn), kind, str(identifier)

    def dispatch(self, conn, data, send, *, operation=None):
        """Prepare before transport; persist only after send succeeds."""
        close_spec = self._CLOSE.get(data.get('type'))
        if close_spec:
            kind, identifier_field = close_spec
            if operation and operation.get('end_reason'):
                self.note_close(conn, kind, data.get(identifier_field), operation['end_reason'])
            return send(data)
        spec = self._OPEN.get(data.get('type'))
        if not spec:
            return send(data)
        kind, id_field = spec
        identifier = str(data.get(id_field) or '')
        if not identifier:
            return send(data)
        if kind == ActivityKind.CLIPBOARD:
            meta = operation or {}
            action = str(meta.get('action') or '')
            args = clipboard_arguments(action, meta.get('arguments'))
            command_type = MSG_TYPE_CLIPBOARD_SET
        else:
            action = ActivityAction.SESSION
            args = {'session_id': identifier}
            if kind == ActivityKind.PTY:
                args['shell'] = str(data.get('shell') or '')
            command_type = kind
        try:
            entry_id = self.history.begin_semantic_execution(
                conn, kind, action, args, command_type=command_type,
            )
        except Exception:
            # Activity storage failure must not prevent a valid Client operation.
            logging.exception('Unable to prepare Client Activity')
            return send(data)
        key = self._key(conn, kind, identifier)
        with self._lock:
            self._active[key] = {
                'conn': conn, 'entry_id': entry_id, 'command_type': command_type,
                'confirmed': False, 'events': [], 'opened': False, 'end_reason': '',
            }
        try:
            result = send(data)
        except Exception:
            with self._lock:
                self._active.pop(key, None)
            self.history.discard_activity_intent(entry_id)
            raise
        with self._lock:
            state = self._active.get(key)
            if state is not None:
                try:
                    self.history.confirm_dispatch(conn, entry_id, '', command_type=command_type)
                    state['confirmed'] = True
                    for event in state['events']:
                        self._apply_event(key, state, event)
                    state['events'].clear()
                except Exception:
                    logging.exception('Unable to confirm Client Activity')
                    self._active.pop(key, None)
        return result

    def received(self, conn, data):
        spec = self._RESULT.get(data.get('type'))
        if not spec:
            return
        kind, field = spec
        key = self._key(conn, kind, data.get(field) or '')
        with self._lock:
            state = self._active.get(key)
            if not state:
                return
            if not state['confirmed']:
                state['events'].append(dict(data))
            else:
                try:
                    self._apply_event(key, state, data)
                except Exception:
                    logging.exception('Unable to update Client Activity')

    def note_close(self, conn, kind, identifier, reason):
        key = self._key(conn, kind, identifier)
        with self._lock:
            state = self._active.get(key)
            if state:
                state['end_reason'] = str(reason or '')

    def disconnected(self, conn):
        with self._lock:
            for key, state in list(self._active.items()):
                if state['conn'] is not conn:
                    continue
                if state['confirmed']:
                    try:
                        self._finish(key, state, 'interrupted', {'end_reason': 'connection_lost'})
                    except Exception:
                        logging.exception('Unable to interrupt Client Activity')
                        self._active.pop(key, None)
                else:
                    self._active.pop(key, None)
                    self.history.discard_activity_intent(state['entry_id'])

    def _apply_event(self, key, state, data):
        kind = key[1]
        event = data.get('type')
        if event in (MSG_TYPE_PTY_OPENED, MSG_TYPE_SCREEN_OPENED):
            state['opened'] = True
            details = {'opened_at': datetime.now().astimezone().isoformat()}
            if kind == ActivityKind.PTY:
                details['shell'] = str(data.get('shell') or '')
            self.history.update_semantic_details(state['conn'], state['entry_id'], details)
        elif event in (MSG_TYPE_PTY_CLOSED, MSG_TYPE_SCREEN_CLOSED):
            details = {'end_reason': state['end_reason'] or ('exited' if kind == ActivityKind.PTY else 'ended')}
            if kind == ActivityKind.PTY:
                details['exit_code'] = data.get('exit_code')
            if not state['opened']:
                details['end_reason'] = 'closed_before_open'
            self._finish(key, state, 'success' if state['opened'] else 'interrupted', details)
        elif event in (MSG_TYPE_PTY_ERROR, MSG_TYPE_SCREEN_ERROR):
            self._finish(key, state, 'error', {
                'end_reason': 'error', 'error': str(data.get('message') or '')[:256],
            })
        elif event == MSG_TYPE_CLIPBOARD_RESULT:
            ok = bool(data.get('ok'))
            status = 'success' if ok else (
                'interrupted' if str(data.get('error') or '') == 'Client disconnected' else 'error'
            )
            try:
                self._finish(key, state, status)
            except Exception:
                logging.exception('Unable to finish Client Activity')
                self._active.pop(key, None)

    def request_failed(self, conn, message_type, request_id, exc):
        if message_type != MSG_TYPE_CLIPBOARD_SET:
            return
        key = self._key(conn, ActivityKind.CLIPBOARD, request_id)
        with self._lock:
            state = self._active.get(key)
            if not state:
                return
            status = ('timed_out' if isinstance(exc, TimeoutError) else
                      'interrupted' if str(exc) == 'Client disconnected' else 'error')
            try:
                self._finish(key, state, status)
            except Exception:
                logging.exception('Unable to finish Client Activity')
                self._active.pop(key, None)

    def _finish(self, key, state, status, details=None):
        self._active.pop(key, None)
        if details:
            try:
                self.history.update_semantic_details(state['conn'], state['entry_id'], details)
            except Exception:
                logging.exception('Unable to save Client Activity details')
        self.history.finalize_execution(
            state['conn'], state['entry_id'], status == 'success', status=status,
        )
