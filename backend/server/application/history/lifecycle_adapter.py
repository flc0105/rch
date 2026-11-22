"""One lifecycle adapter for Client sessions, clipboard requests and file transfers."""
import logging
import threading

from core.protocol.message_types import (
    MSG_TYPE_PTY_OPEN, MSG_TYPE_PTY_OPENED, MSG_TYPE_PTY_CLOSED, MSG_TYPE_PTY_ERROR,
    MSG_TYPE_SCREEN_OPEN, MSG_TYPE_SCREEN_OPENED, MSG_TYPE_SCREEN_CLOSED, MSG_TYPE_SCREEN_ERROR,
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
        self._transfer_service = None

    def bind_transfer_service(self, transfer_service):
        self._transfer_service = transfer_service

    @staticmethod
    def _key(conn, kind, identifier):
        return id(conn), kind, str(identifier)

    def dispatch(self, conn, data, send):
        """Observe only known lifecycle messages; transport remains a pure send."""
        msg_type = data.get('type')
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
                'events': [], 'opened': False,
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

    def disconnected(self, conn):
        with self._lock:
            for key, state in list(self._active.items()):
                if state['conn'] is not conn:
                    continue
                if state['confirmed']:
                    self._finish(key, state, 'interrupted')
                else:
                    self._active.pop(key, None)
                    self.coordinator.drop(state['entry_id'])
            for transfer_id, pair in list(self._transfers.items()):
                if pair[0] is conn:
                    self._finish_transfer(transfer_id, 'interrupted')

    def _apply_event(self, key, state, data):
        event = data.get('type')
        if event in (MSG_TYPE_PTY_OPENED, MSG_TYPE_SCREEN_OPENED):
            state['opened'] = True
        elif event in (MSG_TYPE_PTY_CLOSED, MSG_TYPE_SCREEN_CLOSED):
            self._finish(key, state, 'success' if state['opened'] else 'interrupted')
        elif event in (MSG_TYPE_PTY_ERROR, MSG_TYPE_SCREEN_ERROR):
            self._finish(key, state, 'error')

    def _finish(self, key, state, status):
        self._active.pop(key, None)
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
        self.transfer_updated(service.get_transfer(transfer_id) or transfer)
        return True

    def transfer_updated(self, transfer):
        status = self._TRANSFER_TERMINAL.get(str(transfer.get('state') or ''))
        transfer_id = str(transfer.get('transfer_id') or '')
        if not status:
            return
        with self._lock:
            if transfer_id in self._transfers:
                self._finish_transfer(transfer_id, status, transfer)

    def _finish_transfer(self, transfer_id, status, transfer=None):
        conn, entry_id = self._transfers.pop(transfer_id)
        if transfer is not None:
            artifact_id = str(transfer.get('artifact_id') or '')
            artifact_service = self.coordinator.history_store.artifact_service
            if artifact_id and artifact_service is not None:
                try:
                    artifact = artifact_service.get_artifact_by_id(artifact_id)
                except FileNotFoundError:
                    # An HTTP upload may reach a different Server than the RCH
                    # session. Its Artifact ID is absent from this catalog.
                    logger.warning('Transfer %s references an unknown Artifact %s', transfer_id, artifact_id)
                    status = 'error'
                else:
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
