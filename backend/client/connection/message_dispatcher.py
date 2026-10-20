from core.protocol.message_types import (
    MSG_TYPE_ACMD,
    MSG_TYPE_CANCEL,
    MSG_TYPE_COMMAND,
    MSG_TYPE_HEARTBEAT,
    MSG_TYPE_HEARTBEAT_ACK,
    MSG_TYPE_SCRIPT,
    MSG_TYPE_JOB_CONTROL,
    MSG_TYPE_PTY_OPEN,
    MSG_TYPE_PTY_INPUT,
    MSG_TYPE_PTY_RESIZE,
    MSG_TYPE_PTY_CLOSE,
    MSG_TYPE_SCREEN_OPEN,
    MSG_TYPE_SCREEN_CONFIG,
    MSG_TYPE_SCREEN_CLOSE,
    MSG_TYPE_SCREEN_INPUT,
    MSG_TYPE_CLIPBOARD_GET,
    MSG_TYPE_CLIPBOARD_SET,
    MSG_TYPE_MONITOR_OPEN,
    MSG_TYPE_MONITOR_CONFIG,
    MSG_TYPE_MONITOR_CLOSE,
    MSG_TYPE_TRANSFER_START,
    MSG_TYPE_TRANSFER_CANCEL,
)

class ClientInboundMessageDispatcher:
    """
    Client 侧入站消息调度器。

    职责：
    - 决定消息应立即处理还是交给主线程
    - 复用 message_router 的具体处理逻辑
    - 返回接收线程是否需要立即 send_result
    """

    IMMEDIATE_MESSAGE_TYPES = {MSG_TYPE_HEARTBEAT, MSG_TYPE_HEARTBEAT_ACK, MSG_TYPE_CANCEL, MSG_TYPE_PTY_OPEN, MSG_TYPE_PTY_INPUT, MSG_TYPE_PTY_RESIZE, MSG_TYPE_PTY_CLOSE, MSG_TYPE_SCREEN_OPEN, MSG_TYPE_SCREEN_CONFIG, MSG_TYPE_SCREEN_CLOSE, MSG_TYPE_SCREEN_INPUT, MSG_TYPE_CLIPBOARD_GET, MSG_TYPE_CLIPBOARD_SET, MSG_TYPE_MONITOR_OPEN, MSG_TYPE_MONITOR_CONFIG, MSG_TYPE_MONITOR_CLOSE, MSG_TYPE_TRANSFER_START, MSG_TYPE_TRANSFER_CANCEL}
    DEFERRED_MESSAGE_TYPES = {MSG_TYPE_COMMAND, MSG_TYPE_SCRIPT, MSG_TYPE_ACMD, MSG_TYPE_JOB_CONTROL}

    def __init__(self, connection):
        self.connection = connection

    def dispatch(self, data: dict):
        message_type = data.get('type')

        if message_type in self.IMMEDIATE_MESSAGE_TYPES:
            return self._dispatch_immediate_message(data)

        if message_type in self.DEFERRED_MESSAGE_TYPES:
            return self._dispatch_deferred_message(data)

        return self._dispatch_unknown_message(data)

    def _dispatch_immediate_message(self, data: dict):
        return self.connection.message_router.dispatch(data)

    def _dispatch_deferred_message(self, data: dict):
        self.connection.enqueue_pending_message(data)
        return None

    def _dispatch_unknown_message(self, data: dict):
        return None