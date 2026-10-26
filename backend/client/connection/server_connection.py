import os
import queue

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

    def __init__(self):
        super().__init__()
        self.client_id = None

        self.runtime = ClientRuntime(self)
        self.pending_message_queue = queue.Queue()
        self.is_connected = False

        self.message_router = ClientInboundMessageRouter(self)
        self.message_dispatcher = ClientInboundMessageDispatcher(self)

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

    def report_session_end(self, reason: str, *, command: str = '', summary: str = '', traceback_text: str = ''):
        try:
            message = {'type': MSG_TYPE_SESSION_END, 'reason': reason}
            if command or summary or traceback_text:
                message['detail'] = {
                    key: value for key, value in (
                        ('command', str(command or '')[:200]),
                        ('summary', str(summary or '')[:500]),
                        ('traceback', str(traceback_text or '')[:12000]),
                    ) if value
                }
            self.send(message)
        except OSError:
            pass

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