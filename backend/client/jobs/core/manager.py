import importlib.util
import os
import threading
from typing import Dict, List

from client.jobs.core.runtime import JobRuntime
from client.runtime.sdk.context import use_script_sdk_context
from client.runtime.temp_workspace import cleanup_temp_path
from core.utils.job_metadata import read_job_metadata_from_file, resolve_job_params
from core.utils.reflection import get_main_class


class JobManager:
    """
    后台任务管理器：
    - 加载任务
    - 启动任务
    - 停止任务
    - 查询运行状态
    """

    def __init__(self, socket):
        self.socket = socket
        self._runtimes: Dict[str, JobRuntime] = {}
        self._lock = threading.RLock()

    def normalize_job_name(self, job_name: str) -> str:
        normalized = job_name.strip().replace('\\', '/')
        if not normalized.endswith('.py'):
            normalized += '.py'
        return normalized

    def get_job_key(self, job_name: str) -> str:
        normalized = self.normalize_job_name(job_name)
        return os.path.splitext(os.path.basename(normalized))[0]

    def validate_job_name(self, job_name: str):
        job_key = self.get_job_key(job_name)
        if job_key == 'module':
            raise ValueError('The base job module cannot be started directly')


    def _load_job_instance_from_file(self, full_path: str, job_name: str, command_id: int, job_params=None):
        module_name = self.get_job_key(job_name)
        job_metadata = read_job_metadata_from_file(full_path, fallback_name=module_name)

        try:
            spec = importlib.util.spec_from_file_location(module_name, full_path)
            if spec is None or spec.loader is None:
                raise ImportError(f'Unable to create import spec for: {module_name}')

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            job_class = get_main_class(module, module_name)
            job_instance = job_class()
            resolved_params = resolve_job_params(job_metadata, job_params)
            job_instance.bind_context(
                self.socket,
                command_id,
                client_id=getattr(self.socket, 'client_id', None),
                job_key=self.get_job_key(job_name),
                job_metadata=job_metadata,
                job_params=resolved_params,
            )
            return job_instance
        except Exception as e:
            raise ImportError(f'Failed to load job module "{module_name}": {e}')

    def is_running(self, job_name: str) -> bool:
        job_key = self.get_job_key(job_name)
        with self._lock:
            runtime = self._runtimes.get(job_key)
            return bool(runtime and runtime.is_alive and runtime.job_instance.is_running)

    def get_runtime(self, job_name: str):
        job_key = self.get_job_key(job_name)
        with self._lock:
            return self._runtimes.get(job_key)

    def list_running_jobs(self) -> List[str]:
        with self._lock:
            running = []
            for job_key, runtime in self._runtimes.items():
                if runtime.is_alive:
                    running.append(runtime.display_name)
            return running

    def cleanup_finished_jobs(self):
        with self._lock:
            finished_keys = [
                job_key
                for job_key, runtime in self._runtimes.items()
                if not runtime.is_alive
            ]
            for job_key in finished_keys:
                self._runtimes.pop(job_key, None)

    def start_job(self, full_path: str, job_name: str, command_id: int, job_params=None, cleanup_path: str = '') -> JobRuntime:
        self.cleanup_finished_jobs()
        self.validate_job_name(job_name)

        job_key = self.get_job_key(job_name)
        if self.is_running(job_name):
            raise RuntimeError(f'Job is already running: {job_key}')

        job_instance = self._load_job_instance_from_file(full_path, job_name, command_id, job_params=job_params)

        def _run_job():
            sdk_context = {
                'client_id': job_instance.client_id or '',
                'command_id': job_instance.command_id if job_instance.command_id is not None else '',
                'hostname': job_instance.hostname or '',
                'source_type': 'background_job',
                'source_id': job_instance.job_id,
                'source_name': job_instance.job_key or job_instance.job_name,
                'job_id': job_instance.job_id,
                'job_name': job_instance.job_name,
                'job_key': job_instance.job_key,
            }
            try:
                with use_script_sdk_context(None, {'__context__': sdk_context}):
                    job_instance.run()
            finally:
                if cleanup_path:
                    cleanup_temp_path(cleanup_path)

        thread = threading.Thread(
            target=_run_job,
            name=f'JobThread-{job_key}',
            daemon=True,
        )

        runtime = JobRuntime(
            job_key=job_key,
            job_instance=job_instance,
            thread=thread,
        )

        with self._lock:
            self._runtimes[job_key] = runtime

        thread.start()
        return runtime

    def stop_job(self, job_name: str) -> JobRuntime:
        self.cleanup_finished_jobs()

        runtime = self.get_runtime(job_name)
        if runtime is None:
            raise RuntimeError(f'Job is not running: {self.get_job_key(job_name)}')

        runtime.job_instance.stop()
        runtime.mark_stopped()
        return runtime

    def stop_all_jobs(self) -> List[str]:
        self.cleanup_finished_jobs()
        stopped = []

        with self._lock:
            runtimes = list(self._runtimes.values())

        for runtime in runtimes:
            runtime.job_instance.stop()
            runtime.mark_stopped()
            stopped.append(runtime.display_name)

        return stopped

    def handle_connection_lost(self) -> list[str]:
        """
        连接断开时统一停止所有后台任务。
        注意：此时不要再向服务端发送任何消息。
        """
        stopped = []

        with self._lock:
            runtimes = list(self._runtimes.values())

        for runtime in runtimes:
            try:
                runtime.job_instance.stop(notify=False)
                runtime.mark_stopped()
                stopped.append(runtime.display_name)
            except Exception:
                pass

        return stopped

    def get_job_status(self, job_name: str) -> dict:
        self.cleanup_finished_jobs()

        runtime = self.get_runtime(job_name)
        if runtime is None:
            return {
                'job_name': self.get_job_key(job_name),
                'status': 'not_running',
            }

        return {
            'job_name': runtime.job_key,
            'job_id': runtime.job_instance.job_id,
            'display_name': runtime.display_name,
            'thread_name': runtime.thread.name,
            'is_alive': runtime.is_alive,
            'is_running': runtime.job_instance.is_running,
            'created_at': runtime.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'stopped_at': runtime.stopped_at.strftime('%Y-%m-%d %H:%M:%S') if runtime.stopped_at else '',
            'status': 'running' if runtime.is_alive and runtime.job_instance.is_running else 'stopping',
        }
