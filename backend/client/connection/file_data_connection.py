"""Open a managed auxiliary connection using the active session transport."""
import time
from contextlib import contextmanager

from client.config.config import RUNTIME_CONFIG
from client.connection.transport_connectors import get_connector
from core.protocol.auxiliary import close_socket, send_greeting
from core.protocol.file_stream import DATA_GREETING, IO_TIMEOUT, require_ok
from core.protocol.message_types import MSG_TYPE_TRANSFER_UPDATE
from core.protocol.rchsocket import RCHSocket

@contextmanager
def open_file_data_connection(connection, context, transfer_id, checkpoint):
    token = connection.client_session_token
    if not token:
        raise RuntimeError('Client session token is unavailable')
    packet = {'type': DATA_GREETING, 'transfer_id': transfer_id, 'token': token}
    listener = getattr(connection, 'bind_listener', None)
    raw = None
    wrapper = None
    try:
        checkpoint()
        if listener is not None:
            with listener.expect_file_connection(transfer_id, token) as pending:
                connection.send({'type': MSG_TYPE_TRANSFER_UPDATE,
                                 'transfer_id': transfer_id, 'data_ready': True})
                deadline = time.monotonic() + 15
                while raw is None:
                    checkpoint()
                    raw = pending.take(timeout=0.1)
                    if time.monotonic() >= deadline and raw is None:
                        raise TimeoutError('Timed out waiting for file data connection')
                context.add_cancel_handler(lambda: close_socket(raw))
        else:
            wrapper = RCHSocket()
            wrapper.socket.settimeout(5)
            context.add_cancel_handler(lambda: close_socket(wrapper.socket))
            protocol = str(RUNTIME_CONFIG.get('server_transport') or 'tcp')
            connector = get_connector(protocol)
            connector.validate(RUNTIME_CONFIG)
            address = connection.socket.getpeername()[:2]
            if not connector.connect(wrapper, address, RUNTIME_CONFIG):
                raise ConnectionError('Unable to connect file data socket')
            raw = wrapper.socket
            send_greeting(raw, packet)
        raw.settimeout(IO_TIMEOUT)
        checkpoint()
        require_ok(raw)
        yield raw
    except Exception:
        checkpoint()
        raise
    finally:
        if raw is not None:
            close_socket(raw)
        elif wrapper is not None:
            close_socket(wrapper.socket)

