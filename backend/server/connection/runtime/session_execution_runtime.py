import threading


class SessionExecutionRuntime:
    """
    会话执行运行时。

    职责：
    - 统一保存当前连接的前台执行态
    - 统一保存 command_id -> history_entry_id 绑定
    - 提供命令真正下发时的统一绑定入口
    - 作为 foreground task 与 history binding 的单一运行态对象

    说明：
    - 不负责 socket 收发
    - 不负责消息队列
    - 只负责“单个会话上的执行态”
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._task = None
        self._entry_ids_by_command_id = {}

    # ------------------ foreground task ------------------ #
    def acquire_foreground_task(
        self,
        task_type: str,
        command: str,
        source: str = '',
        task_id: str = '',
        history_entry_id: str = '',
    ) -> dict:
        task_info = {
            'task_type': task_type,
            'command': (command or '').strip(),
            'source': (source or '').strip(),
            'task_id': (task_id or '').strip(),
            'history_entry_id': (history_entry_id or '').strip(),
            'command_id': None,
            'cancel_requested': False,
            'cancel_state': 'running',
        }

        with self._lock:
            if self._task is not None:
                current = self._task
                raise RuntimeError(
                    'Client is busy: '
                    f'{current.get("command") or current.get("task_type") or "running task"}'
                )

            self._task = task_info
            return dict(task_info)

    def bind_foreground_command_id(self, command_id: int):
        with self._lock:
            if self._task is None:
                return None

            self._task['command_id'] = command_id
            return dict(self._task)

    def request_foreground_task_cancel(self, task_id: str = ''):
        task_id = (task_id or '').strip()

        with self._lock:
            if self._task is None:
                return None

            if task_id and self._task.get('task_id') and self._task.get('task_id') != task_id:
                return None

            # A repeated request must not erase a terminal Client acknowledgement.
            if self._task.get('cancel_state') in ('accepted', 'stopped', 'completed'):
                return dict(self._task)

            self._task['cancel_requested'] = True
            self._task['cancel_state'] = 'requested'
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
                self._task['cancel_state'] = state

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

    def get_foreground_task(self):
        with self._lock:
            if self._task is None:
                return None
            return dict(self._task)

    # ------------------ history binding ------------------ #
    def bind_history_entry(self, command_id: int, entry_id: str):
        if not command_id or not entry_id:
            return

        with self._lock:
            self._entry_ids_by_command_id[command_id] = entry_id

    def get_history_entry_id(self, command_id: int) -> str:
        with self._lock:
            return self._entry_ids_by_command_id.get(command_id, '')

    def clear_history_entry(self, command_id: int):
        with self._lock:
            self._entry_ids_by_command_id.pop(command_id, None)

    # ------------------ unified bind ------------------ #
    def bind_command_execution(
        self,
        command_id: int,
        session=None,
        history_entry_id: str = '',
        history_orchestrator=None,
    ):
        """
        命令真正下发时，统一完成：
        - foreground task 绑定 command_id
        - history entry 绑定 command_id

        这里保留最新基线里的 orchestrator 路径：
        - 如果存在 history_orchestrator，则优先通过 orchestrator 绑定
        - 否则直接写入本地 history binding store
        """
        resolved_history_entry_id = (history_entry_id or '').strip()

        with self._lock:
            bound_task = None

            if self._task is not None:
                self._task['command_id'] = command_id
                bound_task = dict(self._task)

                if not resolved_history_entry_id:
                    resolved_history_entry_id = (self._task.get('history_entry_id') or '').strip()

        if resolved_history_entry_id:
            if history_orchestrator is not None and session is not None:
                history_orchestrator.bind_command_entry(
                    session,
                    command_id,
                    resolved_history_entry_id
                )
            else:
                self.bind_history_entry(command_id, resolved_history_entry_id)

        return bound_task








