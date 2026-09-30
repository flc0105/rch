from dataclasses import dataclass, field
from datetime import datetime
from threading import Thread
from typing import Any, Optional

from client.jobs.core.job import Job


@dataclass
class JobRuntime:
    """
    运行中的任务记录。

    inproc 模式持有 job_instance + worker thread；subprocess 模式持有 child process + monitor thread。
    """

    job_key: str
    job_id: str
    job_name: str = ''
    execution_mode: str = 'inproc'
    job_instance: Optional[Job] = None
    thread: Optional[Thread] = None
    process: Optional[Any] = None
    report_context: dict = field(default_factory=dict)
    cleanup_path: str = ''
    created_at: datetime = field(default_factory=datetime.now)
    stopped_at: Optional[datetime] = None
    stop_requested: bool = False

    @property
    def is_alive(self) -> bool:
        if self.execution_mode == 'subprocess':
            return bool(self.process is not None and self.process.poll() is None)
        return bool(self.thread is not None and self.thread.is_alive())

    @property
    def is_running(self) -> bool:
        if self.execution_mode == 'subprocess':
            return self.is_alive and not self.stop_requested
        return bool(self.job_instance is not None and self.job_instance.is_running)

    @property
    def display_name(self) -> str:
        return f'{self.job_key}#{self.job_id[:8]}'

    @property
    def worker_name(self) -> str:
        if self.execution_mode == 'subprocess':
            pid = getattr(self.process, 'pid', None)
            return f'Process-{pid}' if pid else 'Subprocess'
        return getattr(self.thread, 'name', '') or 'Thread'

    def mark_stopped(self):
        self.stop_requested = True
        self.stopped_at = datetime.now()
