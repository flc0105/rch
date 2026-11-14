"""One lifecycle adapter for Client sessions, clipboard requests and file transfers."""
import contextvars
import json
import logging
import threading

from core.protocol.message_types import (
    MSG_TYPE_PTY_OPEN, MSG_TYPE_PTY_CLOSE, MSG_TYPE_PTY_OPENED, MSG_TYPE_PTY_CLOSED, MSG_TYPE_PTY_ERROR,
    MSG_TYPE_SCREEN_OPEN, MSG_TYPE_SCREEN_CLOSE, MSG_TYPE_SCREEN_OPENED, MSG_TYPE_SCREEN_CLOSED, MSG_TYPE_SCREEN_ERROR,
    MSG_TYPE_TRANSFER_START,
)
from server.application.history.activity_definitions import (
    ActivityAction, ActivityKind, ActivityOperation,
)

logger = logging.getLogger(__name__)


class LifecycleAdapter:
    """Correlate dispatched operations with final Client and transfer lifecycle signals."""

    _OPEN = {
        MSG_TYPE_PTY_OPEN: (ActivityKind.PTY, 'pty_session_id'),
        MSG_TYPE_SCREEN_OPEN: (ActivityKind.SCREEN_VIEW, 'screen_session_id'),
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
    }
    _TRANSFER_TERMINAL = {'completed': 'success', 'failed': 'error', 'cancelled': 'cancelled'}
    _DOWNLOAD_SOURCES = {'remote_file_download', 'remote_zip_entry_download', 'remote_file_download_zip'}

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._lock = threading.RLock()
        self._active = {}
        self._transfers = {}
        self._transfer_progress = {}
        self._transfer_service = None
        self._close_scope = contextvars.ContextVar('rch_session_activity_close', default=None)

    def bind_transfer_service(self, transfer_service):
        self._transfer_service = transfer_service

    @staticmethod
    def _key(conn, kind, identifier):
        return id(conn), kind, str(identifier)

    def close_call(self, kind, identifier, reason, execute):
        token = self._close_scope.set((kind, str(identifier), reason))
        try:
            return execute()
        finally:
            self._close_scope.reset(token)

    def dispatch(self, conn, data, send):
        """Observe only known lifecycle messages; transport remains a pure send."""
        msg_type = data.get('type')
        if msg_type in self._CLOSE:
            result = send(data)
            kind, field = self._CLOSE[msg_type]
            close = self._close_scope.get()
            if close is not None and close[:2] == (kind, str(data.get(field) or '')):
                self._note_close(conn, kind, data.get(field), close[2])
            return result
        if msg_type == MSG_TYPE_TRANSFER_START:
            result = send(data)
            try:
                self._transfer_dispatched(conn, data)
            except Exception:
                logger.exception('Unable to create transfer Activity')
            return result
        spec = self._OPEN.get(msg_type)
        if spec is None:
            return send(data)
        kind, field = spec
        identifier = str(data.get(field) or '')
        if not identifier:
            return send(data)
        action = ActivityAction.SESSION
        arguments = {'session_id': identifier}
        if kind == ActivityKind.PTY:
            arguments['shell'] = str(data.get('shell') or '')
        try:
            entry_id = self.coordinator.prepare(conn, ActivityOperation(
                kind, action, arguments))
        except Exception:
            logger.exception('Unable to prepare lifecycle Activity')
            return send(data)
        key = self._key(conn, kind, identifier)
        with self._lock:
            self._active[key] = {
                'conn': conn, 'entry_id': entry_id, 'confirmed': False,
                'events': [], 'opened': False, 'end_reason': '',
            }
        try:
            result = send(data)
        except Exception:
            with self._lock:
                self._active.pop(key, None)
            self.coordinator.drop(entry_id)
            raise
        with self._lock:
            state = self._active.get(key)
            if state is not None:
                try:
                    self.coordinator.dispatch(conn, entry_id, data=data)
                    state['confirmed'] = True
                    for event in state['events']:
                        self._apply_event(key, state, event)
                    state['events'].clear()
                except Exception:
                    logger.exception('Unable to confirm lifecycle Activity')
                    self._active.pop(key, None)
        return result

    def received(self, conn, data):
        spec = self._RESULT.get(data.get('type'))
        if spec is None:
            return
        kind, field = spec
        key = self._key(conn, kind, data.get(field) or '')
        with self._lock:
            state = self._active.get(key)
            if state is None:
                return
            if not state['confirmed']:
                state['events'].append(dict(data))
            else:
                try:
                    self._apply_event(key, state, data)
                except Exception:
                    logger.exception('Unable to update Client Activity')

    def _note_close(self, conn, kind, identifier, reason):
        with self._lock:
            state = self._active.get(self._key(conn, kind, identifier))
            if state:
                state['end_reason'] = str(reason or '')

    def disconnected(self, conn):
        with self._lock:
            for key, state in list(self._active.items()):
                if state['conn'] is not conn:
                    continue
                if state['confirmed']:
                    self._finish(key, state, 'interrupted', {'end_reason': 'connection_lost'})
                else:
                    self._active.pop(key, None)
                    self.coordinator.drop(state['entry_id'])
            for transfer_id, pair in list(self._transfers.items()):
                if pair[0] is conn:
                    self._finish_transfer(transfer_id, 'interrupted', 'Client disconnected')

    def _apply_event(self, key, state, data):
        kind, event = key[1], data.get('type')
        if event in (MSG_TYPE_PTY_OPENED, MSG_TYPE_SCREEN_OPENED):
            state['opened'] = True
            self.coordinator.append_output(state['conn'], state['entry_id'], 1, json.dumps(data, ensure_ascii=False))
        elif event in (MSG_TYPE_PTY_CLOSED, MSG_TYPE_SCREEN_CLOSED):
            scoped = self._close_scope.get()
            scoped_reason = scoped[2] if scoped and scoped[:2] == (kind, key[2]) else ''
            details = {**data, 'end_reason': state['end_reason'] or scoped_reason or ('exited' if kind == ActivityKind.PTY else 'ended')}
            if not state['opened']:
                details['end_reason'] = 'closed_before_open'
            self._finish(key, state, 'success' if state['opened'] else 'interrupted', details)
        elif event in (MSG_TYPE_PTY_ERROR, MSG_TYPE_SCREEN_ERROR):
            self._finish(key, state, 'error', {
                **data, 'end_reason': 'error',
            })
    def _finish(self, key, state, status, details=None):
        self._active.pop(key, None)
        if details:
            self.coordinator.append_output(state['conn'], state['entry_id'], int(status == 'success'), json.dumps(details, ensure_ascii=False), eof=1)
        self.coordinator.finish(state['conn'], state['entry_id'], status == 'success', status=status)

    def _transfer_dispatched(self, conn, data):
        service = self._transfer_service
        transfer_id = str(data.get('transfer_id') or '')
        if service is None or not transfer_id:
            return False
        transfer = service.get_transfer(transfer_id)
        if not transfer:
            return False
        metadata = transfer.get('metadata') or {}
        source = str(metadata.get('source') or '')
        # Previews and unattended internal transfers have no Activity intent.
        if source not in self._DOWNLOAD_SOURCES | {'remote_file_upload', 'cli', 'web', 'web_api', 'rch_cli'}:
            return False
        direction = transfer.get('direction')
        action = 'download_files' if direction == 'client_to_server' else 'upload_files'
        origin = ('cli' if source in {'cli', 'rch_cli'} else 'web_api')
        entry_id = ''
        original_input = ''
        if source in {'cli', 'rch_cli', 'web'}:
            candidate = str(metadata.get('history_entry_id') or '')
            claimed = self.coordinator.claim_upload(conn, candidate)
            if claimed:
                origin, original_input = claimed
                entry_id = candidate
        name = str(transfer.get('filename') or '')
        arguments = {'filename': name, 'count': int(metadata.get('source_count') or 1),
                     'source': source}
        if direction == 'client_to_server':
            arguments['path'] = str(transfer.get('source_path') or '')
        else:
            arguments['destination_path'] = str(transfer.get('destination_path') or '')
            arguments['size'] = transfer.get('total_bytes')
        record = ActivityOperation(ActivityKind.TRANSFER, action, arguments,
                                   origin=origin, presentation='terminal' if origin in {'cli', 'web_terminal'} else 'none',
                                   text=original_input)
        with self._lock:
            if transfer_id in self._transfers:
                return True
            activity_id = self.coordinator.prepare(conn, record, entry_id=entry_id)
            if not activity_id:
                return False
            self.coordinator.dispatch(conn, activity_id, data=data)
            self._transfers[transfer_id] = (conn, activity_id)
            self.coordinator.append_result_event(conn, activity_id, {
                'type': 'result', 'id': transfer_id, 'event_type': 'started',
            })
        self.transfer_updated(service.get_transfer(transfer_id) or transfer)
        return True

    def transfer_updated(self, transfer):
        state = str(transfer.get('state') or '')
        status = self._TRANSFER_TERMINAL.get(state)
        transfer_id = str(transfer.get('transfer_id') or '')
        with self._lock:
            if transfer_id not in self._transfers:
                return
            if not status:
                # Progress is a Result event, not a new transfer wire protocol.
                # Store changes in 10% steps to avoid overwhelming Activity.
                total = transfer.get('total_bytes')
                done = transfer.get('transferred_bytes')
                if isinstance(total, int) and total > 0 and isinstance(done, int):
                    milestone = min(10, max(0, done * 10 // total))
                    if milestone > self._transfer_progress.get(transfer_id, 0):
                        self._transfer_progress[transfer_id] = milestone
                        conn, entry_id = self._transfers[transfer_id]
                        self.coordinator.append_result_event(conn, entry_id, {
                            'type': 'result', 'id': transfer_id, 'event_type': 'progress',
                            'data': {'transferred_bytes': done, 'total_bytes': total},
                        })
                return
            name = str(transfer.get('filename') or 'file')
            count = int((transfer.get('metadata') or {}).get('source_count') or 1)
            size = transfer.get('total_bytes')
            if status == 'success':
                message = f'Transferred {count} items' if count > 1 else f'Transferred {name}'
                if isinstance(size, int):
                    message += f' ({size} bytes)'
            else:
                message = str(transfer.get('error') or ('Transfer cancelled' if status == 'cancelled' else 'Transfer failed'))
            self._finish_transfer(transfer_id, status, message, transfer)

    def _finish_transfer(self, transfer_id, status, message, transfer=None):
        conn, entry_id = self._transfers.pop(transfer_id)
        self._transfer_progress.pop(transfer_id, None)
        event = {'type': 'result', 'id': transfer_id, 'event_type': 'completed',
                 'status': status, 'message': message}
        if transfer is not None and transfer.get('artifact_id'):
            event['references'] = [{'type': 'artifact', 'id': str(transfer['artifact_id'])}]
        self.coordinator.append_result_event(conn, entry_id, event)
        self.coordinator.append_output(conn, entry_id, int(status == 'success'), message)
        if transfer is not None:
            artifact_id = str(transfer.get('artifact_id') or '')
            artifact_service = self.coordinator.history_store.artifact_service
            if artifact_id and artifact_service is not None:
                artifact = artifact_service.get_artifact_by_id(artifact_id)
                if isinstance(artifact, dict) and artifact.get('artifact_id'):
                    self.coordinator.history_store.append_file_for_connection(conn, entry_id, artifact)
        self.coordinator.finish(conn, entry_id, status == 'success', status=status)

    def instrument_artifacts(self, service, connection_lookup):
        """Bind registered Client file references to their dispatched command Activity."""
        import functools
        import inspect

        coordinator = self.coordinator
        methods = frozenset(('save_http_uploaded_file', 'register_command_output_artifact',
                             'save_command_output_artifact'))

        class ArtifactFacade:
            def __getattr__(self, name):
                original = getattr(service, name)
                if name not in methods:
                    return original

                @functools.wraps(original)
                def invoke(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if not isinstance(result, dict) or not result.get('artifact_id'):
                        return result
                    values = inspect.signature(original).bind(*args, **kwargs)
                    values.apply_defaults()
                    client_id = str(values.arguments.get('client_id') or '')
                    source_command_id = values.arguments.get('source_command_id')
                    if client_id and source_command_id is not None:
                        try:
                            conn = connection_lookup(client_id)
                            coordinator.bind_uploaded_artifact(conn, source_command_id, result)
                        except Exception:
                            logger.exception('Unable to attach file reference to command Activity')
                    return result
                return invoke
        return ArtifactFacade()

    def instrument_closes(self, api, *, kind, method, identifier, reason):
        """Declare user-close context at composition, leaving Web APIs as forwarders."""
        import functools
        import inspect

        adapter = self
        class SessionFacade:
            def __getattr__(self, name):
                original = getattr(api, name)
                if name != method:
                    return original

                @functools.wraps(original)
                def invoke(*args, **kwargs):
                    bound = inspect.signature(original).bind(*args, **kwargs)
                    bound.apply_defaults()
                    values = bound.arguments
                    return adapter.close_call(kind, values[identifier], reason(values),
                        lambda: original(*args, **kwargs))
                return invoke
        return SessionFacade()
