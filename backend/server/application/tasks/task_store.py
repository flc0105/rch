import threading
import uuid
from datetime import datetime

from server.application.tasks.task_status import WebTaskStatus
from server.models.records import LifecycleRecordBase


class WebTaskStore:
    """
    Web 任务状态存储。

    职责：
    - 创建任务记录
    - 标记任务完成状态
    - 提供任务查询能力（后续如需扩展）

    新增：
    - tab_id：记录发起当前任务的浏览器页签
    """

    def __init__(self):
        self._tasks = {}
        self._lock = threading.RLock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat()

    def create_task(self, client_id: str, command: str, tab_id: str = '', session_info=None) -> dict:
        """创建任务记录。"""
        task_id = uuid.uuid4().hex
        now = self._now_iso()
        lifecycle = LifecycleRecordBase(
            machine_id=str(getattr(session_info, 'machine_id', '') or ''),
            client_id=str(client_id or getattr(session_info, 'client_id', '') or ''),
            hostname=str(getattr(session_info, 'hostname', '') or ''),
            addr=str(getattr(session_info, 'addr', '') or ''),
            created_at=now,
            started_at=now,
            updated_at=now,
            finished_at='',
        ).to_dict()
        task = {
            **lifecycle,
            'task_id': task_id,
            'command': command,
            'tab_id': (tab_id or '').strip(),
            'status': WebTaskStatus.RUNNING,
            'cancel_requested': False,
            'history_entry_id': '',
        }
        with self._lock:
            self._tasks[task_id] = task
        return task

    def delete_task(self, task_id: str) -> bool:
        """删除任务记录。"""
        normalized_task_id = str(task_id or '').strip()
        if not normalized_task_id:
            return False

        with self._lock:
            return self._tasks.pop(normalized_task_id, None) is not None

    def request_cancel(self, task_id: str) -> dict | None:
        """请求取消任务。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            task['cancel_requested'] = True
            if task.get('status') == WebTaskStatus.RUNNING:
                task['status'] = WebTaskStatus.CANCELLING
            task['updated_at'] = self._now_iso()
            return dict(task)

    def finish_task(self, task_id: str, ok: bool, final_status: str = '') -> None:
        """标记任务完成。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return

            normalized_final_status = str(final_status or '').strip()
            if normalized_final_status in WebTaskStatus.TERMINAL_STATUSES:
                task['status'] = normalized_final_status
            else:
                task['status'] = WebTaskStatus.SUCCESS if ok else WebTaskStatus.ERROR

            finished_at = self._now_iso()
            task['updated_at'] = finished_at
            task['finished_at'] = finished_at

    def is_task_cancelled(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            return task.get('status') == WebTaskStatus.CANCELLED

    def get_task(self, task_id: str):
        """获取任务信息。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return dict(task)

    def all_tasks(self):
        """返回任务快照。"""
        with self._lock:
            return dict(self._tasks)
