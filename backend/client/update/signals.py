"""One-shot authenticated readiness signal for an Update candidate."""
import hmac
import json
import os
import secrets
import socket
import threading
import time

from client.config.config import CLIENT_SOURCE_REVISION

_PORT = 'RCH_UPDATE_SIGNAL_PORT'
_SECRET = 'RCH_UPDATE_SIGNAL_SECRET'
_ATTEMPT = 'RCH_UPDATE_ATTEMPT'
_REPORT_LOCK = threading.Lock()
_reported = False
_recovery_manager = None
_client_watchdog_manager = None


def candidate_environment(port, secret, attempt):
    return {_PORT: str(port), _SECRET: secret, _ATTEMPT: attempt}


def is_update_candidate():
    return bool(os.environ.get(_PORT) and os.environ.get(_SECRET) and os.environ.get(_ATTEMPT))


def set_recovery_manager(manager):
    global _recovery_manager
    _recovery_manager = manager


def set_client_watchdog_manager(manager):
    global _client_watchdog_manager
    _client_watchdog_manager = manager


def _readline(sock):
    data = bytearray()
    while len(data) <= 4096:
        byte = sock.recv(1)
        if byte == b'\n':
            return json.loads(data.decode('utf-8'))
        if not byte:
            break
        data.extend(byte)
    raise ValueError('Invalid Update readiness message')


def report_ready(client_id: str, mode: str):
    """Called at Bind listen() or after Reverse receives its Server token."""
    global _reported
    if not is_update_candidate():
        return
    with _REPORT_LOCK:
        if _reported:
            return
        _reported = True

    def notify():
        try:
            from client.connection.handshake import _get_client_revision_manifest
            revision = CLIENT_SOURCE_REVISION or _get_client_revision_manifest()['revision']
            with socket.create_connection(('127.0.0.1', int(os.environ[_PORT])), timeout=5) as sock:
                sock.settimeout(15)
                sock.sendall((json.dumps({
                    'secret': os.environ[_SECRET],
                    'attempt_id': os.environ[_ATTEMPT],
                    'pid': os.getpid(), 'client_id': str(client_id or ''),
                    'client_revision': revision, 'mode': mode,
                }) + '\n').encode('utf-8'))
                result = _readline(sock)
                if not result.get('accepted'):
                    raise RuntimeError(result.get('error') or 'Update activation was rejected')
            # Activation is now accepted; restore the normal watchdog lifecycle.
            for key in (_PORT, _SECRET, _ATTEMPT):
                os.environ.pop(key, None)
            if _client_watchdog_manager is not None:
                _client_watchdog_manager.start()
            if _recovery_manager is not None:
                from client.config import runtime_config
                if runtime_config.PROCESS_RECOVERY_WATCHDOG_ENABLED:
                    _recovery_manager.start()
        except Exception:
            from core.utils.logger import logger
            logger.exception('Updated Client readiness notification failed')
            os._exit(1)
        finally:
            for key in (_PORT, _SECRET, _ATTEMPT):
                os.environ.pop(key, None)

    threading.Thread(target=notify, name='RCHUpdateReadiness', daemon=True).start()


class SignalListener:
    """Authenticated local acknowledgment; no Server protocol changes."""
    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(1)
        self.sock.settimeout(.25)
        self.port = self.sock.getsockname()[1]
        self.secret = secrets.token_urlsafe(32)
        return self

    def __exit__(self, *_):
        self.sock.close()

    def accept(self, *, attempt_id, process, revision, mode, timeout=45, stable_seconds=2, checkpoint=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if checkpoint is not None:
                checkpoint()
            status = process.poll()
            if status is not None:
                raise RuntimeError(f'Updated Client exited before {mode} readiness (code {status})')
            try:
                connection, _ = self.sock.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(5)
                try:
                    packet = _readline(connection)
                    if not hmac.compare_digest(str(packet.get('secret') or ''), self.secret):
                        raise ValueError('Update signal authentication failed')
                    if (packet.get('attempt_id') != attempt_id
                            or int(packet.get('pid') or -1) != process.pid):
                        raise ValueError('Readiness signal does not match the launched Client')
                    if packet.get('mode') != mode:
                        raise ValueError('Readiness signal connection mode mismatch')
                    if packet.get('client_revision') != revision:
                        raise ValueError('Readiness signal Client revision mismatch')
                    if mode == 'reverse' and not packet.get('client_id'):
                        raise ValueError('Registered Client ID missing')
                    end = time.monotonic() + stable_seconds
                    while time.monotonic() < end:
                        if checkpoint is not None:
                            checkpoint()
                        if process.poll() is not None:
                            raise RuntimeError('Updated Client exited during stabilization')
                        time.sleep(.1)
                    connection.sendall(b'{"accepted":true}\n')
                    return packet
                except Exception as exc:
                    try:
                        connection.sendall((json.dumps({'accepted': False, 'error': str(exc)}) + '\n').encode())
                    except OSError:
                        pass
                    raise
        raise TimeoutError(f'Updated Client did not reach {mode} readiness within {timeout}s')
