"""Independent data sockets for the existing managed Transfer lifecycle."""
import os
import socket
import tempfile
import threading

from core.artifact_contract import ArtifactType
from core.protocol.auxiliary import close_socket, send_greeting
from core.protocol.file_stream import (
    DATA_GREETING, IO_TIMEOUT, receive_control, receive_file, require_ok,
    send_control, send_file,
)
from core.transfer_settings import FileTransferMode
from core.utils.logger import logger
from server.application.artifact.artifact_events import publish_artifact_created


class TcpTransferTransport:
    def __init__(self, transfers, artifacts, tokens, event_bus, *, identity_store=None, max_upload_bytes=None, on_artifact_committed=None):
        self.transfers = transfers
        self.artifacts = artifacts
        self.tokens = tokens
        self.event_bus = event_bus
        self.identity_store = identity_store
        self.max_upload_bytes = max_upload_bytes
        self.on_artifact_committed = on_artifact_committed
        self._lock = threading.RLock()
        self._active = {}  # transfer_id -> (session, socket)

    def _check_identity(self, session, token):
        identity = self.tokens.identify(token)
        if not identity or identity['session'] is not session:
            raise PermissionError('Invalid file data session')
        return identity['client_id']

    def _claim(self, session, transfer_id, sock, token):
        with self._lock:
            client_id = self._check_identity(session, token)
            item = self.transfers.get_transfer(transfer_id)
            if (not item or item['client_id'] != client_id or item['state'] != 'running'
                    or item['metadata'].get('transport') != 'client_transfer_manager'
                    or item['metadata'].get('browser_stage')):
                raise PermissionError('No active managed file transfer')
            if transfer_id in self._active:
                raise ValueError('File data connection already active')
            if len(self._active) >= 64:
                raise RuntimeError('Too many active file data connections')
            self._active[transfer_id] = (session, sock)

    def _release(self, transfer_id, sock):
        with self._lock:
            active = self._active.get(transfer_id)
            if active and active[1] is sock:
                self._active.pop(transfer_id, None)
        close_socket(sock)

    def close_session(self, session):
        with self._lock:
            sockets = [sock for owner, sock in self._active.values() if owner is session]
        for sock in sockets:
            close_socket(sock)

    def accept_reverse(self, sock, packet, listener):
        """Transfer ownership to a worker; the listener must never read file bytes."""
        try:
            token = packet.get('token')
            transfer_id = packet.get('transfer_id')
            if not isinstance(token, str) or not isinstance(transfer_id, str) or not transfer_id:
                raise ValueError('Invalid file data greeting')
            identity = self.tokens.identify(token)
            if not identity:
                raise PermissionError('Invalid file data session')
            session = identity['session']
            if (getattr(session, 'listener_id', None) != listener.listener_id
                    or getattr(session, 'listener_protocol', None) != listener.protocol):
                raise PermissionError('File data connection must use its session listener')
            self._claim(session, transfer_id, sock, token)
        except Exception:
            close_socket(sock)
            return
        try:
            threading.Thread(target=self._run, args=(session, transfer_id, sock, token),
                             daemon=True, name='TcpFileTransfer').start()
        except Exception:
            self._release(transfer_id, sock)
            raise

    def start_bind(self, session, transfer_id):
        if getattr(session, 'listener_protocol', None) != 'bind_tcp':
            return
        token = getattr(session.context, 'client_session_token', '')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._check_identity(session, token)
            self._claim(session, transfer_id, sock, token)
        except Exception:
            close_socket(sock)
            return
        try:
            threading.Thread(target=self._run, args=(session, transfer_id, sock, token),
                             kwargs={'dial': True}, daemon=True, name='TcpFileTransfer').start()
        except Exception:
            self._release(transfer_id, sock)
            raise

    def _run(self, session, transfer_id, sock, token, *, dial=False):
        client_id = session.session_info.client_id
        authorized = False
        try:
            self._check_identity(session, token)
            # Reverse data may arrive just before its mode snapshot on the main socket.
            item = self.transfers.wait_for_tcp_transfer(transfer_id, client_id, timeout=5)
            if not item:
                raise PermissionError('No active managed TCP transfer')
            authorized = True
            if dial:
                sock.settimeout(5)
                sock.connect(session.bind_dial_endpoint)
                if getattr(session, 'bind_transport', 'tcp') == 'mtls_tcp':
                    sock = self.identity_store.wrap_outbound_socket(sock)
                    with self._lock:
                        self._active[transfer_id] = (session, sock)
                send_greeting(sock, {'type': DATA_GREETING, 'transfer_id': transfer_id, 'token': token})
            sock.settimeout(IO_TIMEOUT)
            self._checkpoint(transfer_id, session, token)
            send_control(sock, {'ok': True})
            if item['direction'] == 'client_to_server':
                self._receive(session, transfer_id, sock, token)
            elif item['direction'] == 'server_to_client':
                self._send(session, transfer_id, sock, token, item)
            else:
                raise ValueError('Invalid transfer direction')
        except Exception as exc:
            close_socket(sock)
            if authorized:
                # The Client owns its cancellation outcome and local commit. A
                # closed data socket can precede the terminal main-channel event.
                current = self.transfers.get_transfer(transfer_id)
                # Cancellation can close data I/O before its terminal control
                # message arrives. Give that outcome the existing I/O deadline.
                pending_cancel = current and current['stage'] == 'cancelling'
                terminal = self.transfers.wait_for_terminal(
                    transfer_id, timeout=IO_TIMEOUT if pending_cancel else 2)
                if terminal and terminal['state'] == 'running':
                    self.transfers.fail_transfer(transfer_id, str(exc), client_id=client_id)
                logger.debug('TCP file transfer %s: %s', transfer_id, exc)
        finally:
            self._release(transfer_id, sock)

    def _checkpoint(self, transfer_id, session, token):
        client_id = self._check_identity(session, token)
        item = self.transfers.get_transfer(transfer_id)
        if not item or item['client_id'] != client_id or item['state'] != 'running':
            raise ConnectionError('File transfer is no longer active')
        # A pending Cancel must reach the Client context before data I/O is
        # interrupted. Otherwise a normal cancellation looks like socket failure.
        # The receiving Server still checks cancellation at its commit boundary.

    def _receive(self, session, transfer_id, sock, token):
        header = receive_control(sock)
        size = header.get('size')
        if (type(size) is not int or size < 0
                or (self.max_upload_bytes is not None and size > self.max_upload_bytes)):
            raise ValueError('Invalid file size or upload limit exceeded')
        filename = header.get('filename')
        if (not isinstance(filename, str) or not filename or '\x00' in filename
                or '/' in filename or '\\' in filename or filename in ('.', '..')):
            raise ValueError('Invalid artifact filename')
        artifact_type = ArtifactType(header.get('artifact_type'))
        if artifact_type not in (ArtifactType.SAVED, ArtifactType.PREVIEW):
            raise ValueError('Invalid managed transfer artifact type')
        category = header.get('category') or ''
        extra = header.get('extra') or {}
        if not isinstance(category, str) or not isinstance(extra, dict):
            raise ValueError('Invalid artifact metadata')
        if artifact_type == ArtifactType.PREVIEW and category:
            raise ValueError('Only Saved Files can have category')
        info = session.session_info
        item = self.transfers.get_transfer(transfer_id) or {}
        command_id = (item.get('metadata') or {}).get('source_command_id')
        allocated = self.artifacts.allocate_artifact_path(artifact_type.value, info.machine_id, filename)
        path = allocated['file_path']
        fd, staged = tempfile.mkstemp(prefix='.rch-transfer-', dir=os.path.dirname(path))
        os.close(fd)
        registered = False
        try:
            size = receive_file(sock, staged, header,
                                checkpoint=lambda: self._checkpoint(transfer_id, session, token))
            self._checkpoint(transfer_id, session, token)

            def commit():
                nonlocal registered
                os.replace(staged, path)
                artifact = self.artifacts.register_existing_artifact(
                    artifact_type=artifact_type.value, category=category,
                    hostname=info.hostname, machine_id=allocated['machine_id'],
                    original_name=filename, file_path=path, artifact_id=allocated['artifact_id'],
                    client_id=info.client_id, addr=info.addr, extra=extra,
                    **({'source_command_id': command_id} if command_id is not None else {}),
                )
                registered = True
                return artifact

            try:
                artifact = self.transfers.commit_tcp_artifact(
                    transfer_id, info.client_id, filename, size, commit)
            except Exception:
                # Registration precedes terminal history persistence. Compensate
                # only our new Artifact if the terminal commit did not succeed.
                current = self.transfers.get_transfer(transfer_id)
                if registered and (not current or current['state'] != 'completed'):
                    try:
                        self.artifacts.delete_artifact(allocated['artifact_id'])
                        registered = False
                    except Exception:
                        logger.exception('Unable to roll back TCP artifact registration')
                raise
            try:
                publish_artifact_created(self.event_bus, artifact)
            except Exception:
                logger.exception('Unable to publish TCP artifact creation')
            if self.on_artifact_committed is not None:
                try:
                    self.on_artifact_committed(session, artifact, command_id)
                except Exception:
                    logger.exception('Unable to publish TCP artifact commit')
            # Return the same public metadata needed by Clipboard image previews.
            send_control(sock, {'ok': True, 'data': artifact})
        finally:
            if os.path.exists(staged):
                os.unlink(staged)
            if not registered and os.path.exists(path):
                os.unlink(path)

    def _send(self, session, transfer_id, sock, token, item):
        # Source path is the Server's own staged file, never a data-socket parameter.
        path = item['source_path']
        size = send_file(sock, path, checkpoint=lambda: self._checkpoint(transfer_id, session, token))
        ack = require_ok(sock)
        if ack.get('size') != size:
            raise ValueError('Invalid file commit acknowledgement')
        # Client reports the committed destination path via the existing terminal update.
        terminal = self.transfers.wait_for_terminal(transfer_id, timeout=IO_TIMEOUT)
        if terminal and terminal['state'] == 'running':
            raise TimeoutError('Client did not report file transfer completion')
