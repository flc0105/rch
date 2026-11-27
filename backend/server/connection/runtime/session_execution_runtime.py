import logging
import threading
from datetime import datetime, timezone


class SessionExecutionRuntime:
    """
    会话执行运行时。

    职责：
    - 统一保存当前连接的前台执行态
    - 提供命令真正下发时的统一绑定入口

    说明：
    - 不负责 socket 收发
    - 不负责消息队列
    - 只负责“单个会话上的执行态”
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._task_changed_listener = None
        self._task = None

    def set_foreground_task_listener(self, listener):
        with self._lock:
            self._task_changed_listener = listener

    def _notify_task_changed(self):
        # Emit while holding the task lock, so a fast task cannot publish
        # Running after a later Idle transition.
        if self._task_changed_listener is not None:
            try:
                self._task_changed_listener()
            except Exception:
                logging.getLogger(__name__).warning('Unable to publish foreground task', exc_info=True)

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
        task_info = {
            'started_at': datetime.now(timezone.utc).isoformat(),
            'task_type': task_type,
            'command': (command or '').strip(),
            'source': (source or '').strip(),
            'task_id': (task_id or '').strip(),
            'web_task': bool(web_task),
            'tab_id': (tab_id or '').strip(),
            'command_id': None,
            'cancel_requested': False,
            'cancel_state': 'running',
            'cancel_policy': cancel_policy,
        }

        with self._lock:
            if self._task is not None:
                raise RuntimeError('Another operation is running on this client. Please try again when it finishes.')

            self._task = task_info
            self._notify_task_changed()
            return dict(task_info)

    def set_foreground_cancel_policy(self, policy):
        with self._lock:
            if self._task is not None:
                self._task['cancel_policy'] = policy
                self._notify_task_changed()

    def bind_foreground_command_id(self, command_id: int):
        with self._lock:
            if self._task is None:
                return None

            if self._task['command_id'] != command_id:
                self._task['command_id'] = command_id
                self._notify_task_changed()
            return dict(self._task)

    def unbind_foreground_command_id(self, command_id: int):
        with self._lock:
            if self._task is not None and self._task.get('command_id') == command_id:
                self._task['command_id'] = None
                self._notify_task_changed()

    def request_foreground_task_cancel(self, task_id: str = ''):
        task_id = (task_id or '').strip()

        with self._lock:
            if self._task is None:
                return None

            if task_id and self._task.get('task_id') and self._task.get('task_id') != task_id:
                return None

            # A repeated request must not erase a terminal Client acknowledgement.
            if self._task.get('cancel_state') in ('requested', 'accepted', 'stopped', 'completed'):
                return dict(self._task)

            self._task['cancel_requested'] = True
            self._task['cancel_state'] = 'requested'
            self._notify_task_changed()
            return dict(self._task)

    def record_cancel_ack(self, command_id: int, state: str):
        # Acknowledgement and actual termination are different states.
        if state not in ('accepted', 'rejected', 'stopped', 'completed'):
            return
        with self._lock:
            if self._task is None or self._task.get('command_id') != command_id:
                return
            # A delayed 'accepted' acknowledgement must not overwrite a terminal state.
            if self._task.get('cancel_state') not in ('stopped', 'completed'):
                if self._task['cancel_state'] != state or (state == 'rejected' and self._task['cancel_requested']):
                    self._task['cancel_state'] = state
                    if state == 'rejected':
                        self._task['cancel_requested'] = False
                    self._notify_task_changed()

    def release_foreground_task(self, task_id: str = '', command: str = '') -> None:
        task_id = (task_id or '').strip()
        command = (command or '').strip()

        with self._lock:
            if self._task is None:
                return

            current = self._task

            if task_id and current.get('task_id') and current.get('task_id') != task_id:
                return

            if command and current.get('command') and current.get('command') != command:
                return

            self._task = None
            self._notify_task_changed()

    def get_foreground_task(self):
        with self._lock:
            if self._task is None:
                return None
            return dict(self._task)
