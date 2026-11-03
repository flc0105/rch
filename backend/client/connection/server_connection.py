import os
import queue
import threading
import uuid

from client.connection.message_dispatcher import ClientInboundMessageDispatcher
from client.connection.message_router import ClientInboundMessageRouter
from client.runtime.client_runtime import ClientRuntime
from core.protocol.message_types import MSG_TYPE_RESULT, MSG_TYPE_SESSION_END
from core.protocol.rchsocket import RCHSocket
from core.utils.logger import logger


class ServerConnection(RCHSocket):
    """
    客户端与服务端的连接类。

    当前承载：
    - 普通消息收发
    - 命令执行结果回传
    - 入站消息分发与路由

    本地运行能力统一放在 ClientRuntime 中，避免连接层继续膨胀。
    """

    SESSION_END_ACK_TIMEOUT_SECONDS = 2.0

    def __init__(self, *, features=None):
        super().__init__()
        self.client_id = None

        self.runtime = ClientRuntime(self, features=features)
        self.pending_message_queue = queue.Queue()
        self.is_connected = False
        self._pause_requested = False
        self._session_end_lock = threading.Lock()
        self._session_end_ack = threading.Event()
        self._pending_session_end_id = ''

        self.message_router = ClientInboundMessageRouter(self)
        self.message_dispatcher = ClientInboundMessageDispatcher(self)

    def request_pause(self):
        # Applied by Client.wait only after the final result frame is sent.
        self._pause_requested = True

    def consume_pause_request(self):
        requested = self._pause_requested
        self._pause_requested = False
        return requested

    def mark_connected(self):
        self.is_connected = True

    def mark_disconnected(self):
        self.is_connected = False

    def reset_runtime_state(self):
        try:
            while True:
                self.pending_message_queue.get_nowait()
        except queue.Empty:
            pass
        except Exception:
            pass

    def acknowledge_session_end(self, end_id: str):
        if end_id and end_id == self._pending_session_end_id:
            self._session_end_ack.set()

    def report_session_end(self, reason: str, *, command: str = '', summary: str = '', traceback_text: str = '') -> bool:
        """Report an intentional exit and wait until Server has recorded its reason.

        The existing receiver thread processes the ACK. A bounded timeout avoids
        holding shutdown indefinitely when the transport is already broken.
        """
        with self._session_end_lock:
            end_id = uuid.uuid4().hex
            self._pending_session_end_id = end_id
            self._session_end_ack.clear()
            message = {'type': MSG_TYPE_SESSION_END, 'reason': reason, 'end_id': end_id}
            if command or summary or traceback_text:
                message['detail'] = {
                    key: value for key, value in (
                        ('command', str(command or '')[:200]),
                        ('summary', str(summary or '')[:500]),
                        ('traceback', str(traceback_text or '')[:12000]),
                    ) if value
                }
            try:
                self.send(message)
                if not self.is_connected:
                    return False
                acknowledged = self._session_end_ack.wait(self.SESSION_END_ACK_TIMEOUT_SECONDS)
                if not acknowledged:
                    logger.warning('Session end not acknowledged by Server: reason=%s', reason)
                return acknowledged
            except OSError as exc:
                logger.warning('Session end could not be reported: reason=%s error=%s', reason, exc)
                return False
            finally:
                self._pending_session_end_id = ''

    def send_result(self, id: int, status: int, result: str, eof: int = 1):
        data = {
            'type': MSG_TYPE_RESULT,
            'id': id,
            'status': status,
            'text': result,
            'cwd': os.getcwd(),
            'eof': eof,
        }
        logger.debug(data)
        self.send(data)

    def enqueue_pending_message(self, data: dict):
        self.pending_message_queue.put(data)

    def handle_received_message(self, data: dict):
        logger.debug(data)
        return self.message_dispatcher.dispatch(data)

    def recv_message(self):
        data = self.recv()
        result = self.handle_received_message(data)
        if result:
            self.send_result(*result)

    def recv_command(self, timeout: float | None = None):
        data = self.pending_message_queue.get(timeout=timeout)

        try:
            return self.message_router.dispatch(data)
        except Exception as e:
            logger.error(e, exc_info=True)
            return data.get('id'), 0, f'{e}\n'