from core.utils.logger import logger


class ServerResultDispatcher:
    """
    Server 侧结果分发器。

    职责：
    - 判断结果是否属于当前等待中的命令
    - 将预期结果写入结果队列
    - 将非预期结果转成背景消息或未读消息
    """

    def __init__(self, session):
        self.session = session

    def dispatch_result(self, command_id, status, text, end, before_enqueue=None):
        """
        分发命令执行结果
        """
        if self.session.runtime.pending_results.deliver(command_id, status, text, end, before_enqueue):
            return True
        # A late/duplicate result must never enter another request's stream.
        if command_id is not None and command_id != 0:
            return False
        if before_enqueue is not None:
            before_enqueue()
        self._handle_unexpected_message(status, text, end)
        return True

    def _handle_unexpected_message(self, status, text, end):
        """
        处理非预期消息
        """
        callback = self.session.context.on_unexpected_message
        if callable(callback):
            try:
                callback(status, text, end)
                return
            except Exception:
                pass

        # 如果交互态 且开启了背景消息写文件
        # session_messages.log 已移除；没有上层 callback 时直接输出到控制台。
        if self.session.context.is_interactive:
            logger.info(text)
            return

        # 非交互态开了背景消息写文件 就只记录到文件 不存未读消息
        # 文件日志已移除；没有上层 callback 时继续沿用未读消息队列兜底。
        # 如果非交互态 没开背景消息 收到消息 直接存储到未读消息
        self.session.runtime.message_queue.put(status, text, end)
