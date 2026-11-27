from core.protocol.result_envelope import ResultEvent
from typing import Optional

from core.protocol.message_queue import MessageQueue
from server.connection.runtime.pending_results import PendingResults
import queue
import time
from server.connection.runtime.session_execution_runtime import SessionExecutionRuntime


class ClientSessionRuntime:
    """
    客户端会话运行时。

    职责：
    - 保存与本次连接会话相关的运行状态
    - 不直接负责 socket 收发
    - 为 ClientSession / CommandChannel 提供运行态存取能力

    当前承载：
    - pending_results
    - message_queue
    - execution_runtime
    """

    def __init__(self):
        self.pending_results = PendingResults()
        self.message_queue = MessageQueue()
        self._execution_runtime = SessionExecutionRuntime()

    def set_foreground_task_listener(self, listener):
        self._execution_runtime.set_foreground_task_listener(listener)

    # ------------------ foreground task ------------------ #
    def acquire_foreground_task(
        self,
        task_type: str,
        command: str,
        source: str = '',
        task_id: str = '',
        web_task: bool = False,
        tab_id: str = '',
        cancel_policy: str = '',
    ) -> dict:
        """
        尝试占用当前连接的前台执行槽。
        """
        return self._execution_runtime.acquire_foreground_task(
            task_type=task_type,
            command=command,
            source=source,
            task_id=task_id,
            web_task=web_task,
            tab_id=tab_id,
            cancel_policy=cancel_policy,
        )

    def set_foreground_cancel_policy(self, policy):
        self._execution_runtime.set_foreground_cancel_policy(policy)

    def bind_foreground_command_id(self, command_id: int):
        """
        将实际下发的 command_id 绑定到当前前台任务
        """
        return self._execution_runtime.bind_foreground_command_id(command_id)

    def unbind_foreground_command_id(self, command_id: int):
        return self._execution_runtime.unbind_foreground_command_id(command_id)

    def request_foreground_task_cancel(self, task_id: str = ''):
        """
        请求取消当前前台任务
        """
        return self._execution_runtime.request_foreground_task_cancel(task_id=task_id)

    def record_cancel_ack(self, command_id: int, state: str):
        self._execution_runtime.record_cancel_ack(command_id, state)

    def release_foreground_task(self, task_id: str = '', command: str = '') -> None:
        """
        释放当前连接的前台执行槽。
        """
        self._execution_runtime.release_foreground_task(task_id=task_id, command=command)

    def get_foreground_task(self):
        """
        获取当前前台任务快照
        """
        return self._execution_runtime.get_foreground_task()

    # ------------------ result wait ------------------ #
    def wait_for_result(self, connection, command_id: int, command: Optional[str], *, results=None, timeout=None):
        """
        等待并返回对应命令的结果事件
        """
        if results is None:
            results = self.pending_results.register(command_id)
        deadline = time.monotonic() + timeout if timeout is not None else None
        try:
            while 1:
                try:
                    event = results.get(timeout=max(0, deadline - time.monotonic()) if deadline is not None else None)
                except queue.Empty:
                    self.pending_results.remove(command_id)
                    try:
                        connection.send_cancel(command_id)
                    except OSError:
                        pass
                    raise TimeoutError('Control request timed out') from None
                if event is None:
                    interrupted = {
                        'event_type': 'completed', 'status': 'interrupted', 'message': 'Client disconnected',
                    }
                    yield ResultEvent(interrupted)
                    break
                result = ResultEvent(event)
                yield result
                if result.terminal_status is not None:
                    break
        finally:
            self.pending_results.remove(command_id)
