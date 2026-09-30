import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from typing import Dict, List

from client.config.config import RUNTIME_CONFIG
from client.http.client_api import ClientApiClient
from client.jobs.core.runtime import JobRuntime
from client.runtime.sdk.context import use_script_sdk_context
from client.runtime.temp_workspace import cleanup_temp_path
from core.utils.job_metadata import (
    normalize_job_execution_mode,
    read_job_metadata_from_file,
    resolve_job_params,
)
from core.utils.reflection import get_main_class


class JobManager:
    """
    后台任务管理器：
    - 加载任务
    - 启动任务（进程内线程 / 独立子进程）
    - 停止任务
    - 查询运行状态
    """

    SUBPROCESS_STOP_GRACE_SECONDS = 3.0
    SUBPROCESS_TERMINATE_GRACE_SECONDS = 2.0

    def __init__(self, socket):
        self.socket = socket
        self._runtimes: Dict[str, JobRuntime] = {}
        self._lock = threading.RLock()
        self.client_api = ClientApiClient()

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

    def _socket_info(self) -> dict:
        try:
            info = getattr(self.socket, 'info', {}) or {}
            return dict(info) if isinstance(info, dict) else {}
        except Exception:
            return {}

    def _resolve_job_definition(self, full_path: str, job_name: str, job_params=None, execution_mode=''):
        module_name = self.get_job_key(job_name)
        job_metadata = read_job_metadata_from_file(full_path, fallback_name=module_name)
        resolved_params = resolve_job_params(job_metadata, job_params)

        metadata_default = str((job_metadata or {}).get('execution_mode') or 'inproc').strip() or 'inproc'
        resolved_mode = normalize_job_execution_mode(execution_mode, default=metadata_default)
        return job_metadata, resolved_params, resolved_mode

    def _load_job_instance_from_file(
        self,
        full_path: str,
        job_name: str,
        command_id: int,
        *,
        job_metadata: dict,
        resolved_params: dict,
        execution_mode: str,
        job_id: str = '',
    ):
        module_name = self.get_job_key(job_name)

        try:
            spec = importlib.util.spec_from_file_location(module_name, full_path)
            if spec is None or spec.loader is None:
                raise ImportError(f'Unable to create import spec for: {module_name}')

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            job_class = get_main_class(module, module_name)
            job_instance = job_class()
            if job_id:
                job_instance.job_id = job_id
            job_instance.bind_context(
                self.socket,
                command_id,
                client_id=getattr(self.socket, 'client_id', None),
                job_key=self.get_job_key(job_name),
                job_metadata=job_metadata,
                job_params=resolved_params,
                execution_mode=execution_mode,
            )
            return job_instance
        except Exception as e:
            raise ImportError(f'Failed to load job module "{module_name}": {e}')

    def _build_sdk_context(self, job_instance) -> dict:
        return {
            'client_id': job_instance.client_id or '',
            'command_id': job_instance.command_id if job_instance.command_id is not None else '',
            'hostname': job_instance.hostname or '',
            'source_type': 'background_job',
            'source_id': job_instance.job_id,
            'source_name': job_instance.job_key or job_instance.job_name,
            'job_id': job_instance.job_id,
            'job_name': job_instance.job_name,
            'job_key': job_instance.job_key,
            'execution_mode': job_instance.execution_mode,
        }

    def is_running(self, job_name: str) -> bool:
        job_key = self.get_job_key(job_name)
        with self._lock:
            runtime = self._runtimes.get(job_key)
            return bool(runtime and runtime.is_alive and runtime.is_running)

    def get_runtime(self, job_name: str):
        job_key = self.get_job_key(job_name)
        with self._lock:
            return self._runtimes.get(job_key)

    def list_running_jobs(self) -> List[str]:
        with self._lock:
            running = []
            for runtime in self._runtimes.values():
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

    def start_job(
        self,
        full_path: str,
        job_name: str,
        command_id: int,
        job_params=None,
        cleanup_path: str = '',
        execution_mode: str = '',
    ) -> JobRuntime:
        self.cleanup_finished_jobs()
        self.validate_job_name(job_name)

        job_key = self.get_job_key(job_name)
        if self.is_running(job_name):
            raise RuntimeError(f'Job is already running: {job_key}')

        job_metadata, resolved_params, resolved_mode = self._resolve_job_definition(
            full_path,
            job_name,
            job_params=job_params,
            execution_mode=execution_mode,
        )

        if resolved_mode == 'subprocess':
            return self._start_subprocess_job(
                full_path,
                job_name,
                command_id,
                job_metadata=job_metadata,
                resolved_params=resolved_params,
                cleanup_path=cleanup_path,
            )

        return self._start_inproc_job(
            full_path,
            job_name,
            command_id,
            job_metadata=job_metadata,
            resolved_params=resolved_params,
            cleanup_path=cleanup_path,
        )

    def _start_inproc_job(
        self,
        full_path: str,
        job_name: str,
        command_id: int,
        *,
        job_metadata: dict,
        resolved_params: dict,
        cleanup_path: str,
    ) -> JobRuntime:
        job_key = self.get_job_key(job_name)
        job_instance = self._load_job_instance_from_file(
            full_path,
            job_name,
            command_id,
            job_metadata=job_metadata,
            resolved_params=resolved_params,
            execution_mode='inproc',
        )

        def _run_job():
            try:
                with use_script_sdk_context(None, {'__context__': self._build_sdk_context(job_instance)}):
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
            job_id=job_instance.job_id,
            job_name=job_instance.job_name,
            execution_mode='inproc',
            job_instance=job_instance,
            thread=thread,
            cleanup_path=cleanup_path,
        )

        with self._lock:
            self._runtimes[job_key] = runtime

        thread.start()
        return runtime

    def _start_subprocess_job(
        self,
        full_path: str,
        job_name: str,
        command_id: int,
        *,
        job_metadata: dict,
        resolved_params: dict,
        cleanup_path: str,
    ) -> JobRuntime:
        job_key = self.get_job_key(job_name)
        job_id = str(uuid.uuid4())
        socket_info = self._socket_info()
        client_id = str(getattr(self.socket, 'client_id', '') or '').strip()
        hostname = str(socket_info.get('hostname') or '').strip()

        context = {
            'job_path': os.path.abspath(full_path),
            'job_name': job_name,
            'job_key': job_key,
            'job_id': job_id,
            'command_id': command_id,
            'client_id': client_id,
            'hostname': hostname,
            'job_metadata': dict(job_metadata or {}),
            'job_params': dict(resolved_params or {}),
            'execution_mode': 'subprocess',
        }

        context_dir = cleanup_path or os.path.dirname(os.path.abspath(full_path))
        os.makedirs(context_dir, exist_ok=True)
        context_path = os.path.join(context_dir, 'job_subprocess_context.json')
        with open(context_path, 'w', encoding='utf-8') as file_obj:
            json.dump(context, file_obj, ensure_ascii=False)

        runner_path = os.path.join(os.path.dirname(__file__), 'subprocess_runner.py')
        args = [sys.executable, runner_path, '--context-file', context_path]
        profile_name = str((RUNTIME_CONFIG or {}).get('profile_name') or '').strip()
        if profile_name:
            args.extend(['--profile', profile_name])

        backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        env = os.environ.copy()
        existing_pythonpath = str(env.get('PYTHONPATH') or '').strip()
        env['PYTHONPATH'] = backend_root + (os.pathsep + existing_pythonpath if existing_pythonpath else '')

        popen_kwargs = {
            'stdin': subprocess.PIPE,
            'text': True,
            'bufsize': 1,
            'cwd': backend_root,
            'env': env,
        }
        if os.name == 'nt':
            popen_kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        else:
            popen_kwargs['start_new_session'] = True

        try:
            process = subprocess.Popen(args, **popen_kwargs)
        except Exception:
            if cleanup_path:
                cleanup_temp_path(cleanup_path)
            raise

        report_context = {
            'client_id': client_id,
            'command_id': command_id,
            'job_id': job_id,
            'job_name': str(job_metadata.get('name') or job_key).strip() or job_key,
            'job_key': job_key,
            'display_name': f'{job_key}#{job_id[:8]}',
            'thread_name': f'Process-{process.pid}',
            'execution_mode': 'subprocess',
            'params': dict(resolved_params or {}),
        }

        runtime = JobRuntime(
            job_key=job_key,
            job_id=job_id,
            job_name=report_context['job_name'],
            execution_mode='subprocess',
            process=process,
            report_context=report_context,
            cleanup_path=cleanup_path,
        )

        monitor = threading.Thread(
            target=self._monitor_subprocess,
            args=(runtime,),
            name=f'JobProcessMonitor-{job_key}',
            daemon=True,
        )
        runtime.thread = monitor

        with self._lock:
            self._runtimes[job_key] = runtime

        monitor.start()
        return runtime

    def _post_subprocess_terminal_state(self, runtime: JobRuntime, returncode: int):
        payload = dict(runtime.report_context or {})
        if not payload.get('client_id'):
            return

        if runtime.stop_requested or returncode == 0:
            state = 'stopped'
            status = 1
            text = 'Job subprocess stopped' if runtime.stop_requested else 'Job subprocess exited'
        else:
            state = 'error'
            status = 0
            text = f'Job subprocess exited unexpectedly with code {returncode}'

        payload.update({
            'event_type': 'status',
            'state': state,
            'status': status,
            'text': text,
        })
        try:
            self.client_api.post_background_job_report(payload, timeout=10)
        except Exception:
            pass

    def _monitor_subprocess(self, runtime: JobRuntime):
        process = runtime.process
        returncode = -1
        try:
            returncode = process.wait() if process is not None else -1
            self._post_subprocess_terminal_state(runtime, returncode)
        finally:
            runtime.stopped_at = runtime.stopped_at or datetime.now()
            if runtime.cleanup_path:
                cleanup_temp_path(runtime.cleanup_path)

    def _terminate_process_tree(self, process, *, force: bool = False):
        if process is None or process.poll() is not None:
            return

        try:
            if os.name == 'nt':
                if force:
                    subprocess.run(
                        ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    process.terminate()
                return

            sig = signal.SIGKILL if force else signal.SIGTERM
            os.killpg(os.getpgid(process.pid), sig)
        except Exception:
            try:
                process.kill() if force else process.terminate()
            except Exception:
                pass

    def _force_stop_subprocess_after_grace(self, runtime: JobRuntime):
        process = runtime.process
        if process is None:
            return
        try:
            process.wait(timeout=self.SUBPROCESS_STOP_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass

        self._terminate_process_tree(process, force=False)
        try:
            process.wait(timeout=self.SUBPROCESS_TERMINATE_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            self._terminate_process_tree(process, force=True)

    def _request_subprocess_stop(self, runtime: JobRuntime, *, notify: bool):
        runtime.mark_stopped()
        process = runtime.process
        if process is None or process.poll() is not None:
            return

        command = 'stop' if notify else 'stop_silent'
        try:
            if process.stdin is not None:
                process.stdin.write(command + '\n')
                process.stdin.flush()
        except Exception:
            pass

        threading.Thread(
            target=self._force_stop_subprocess_after_grace,
            args=(runtime,),
            name=f'JobProcessStop-{runtime.job_key}',
            daemon=True,
        ).start()

    def _request_runtime_stop(self, runtime: JobRuntime, *, notify: bool = True):
        if runtime.execution_mode == 'subprocess':
            self._request_subprocess_stop(runtime, notify=notify)
            return

        if runtime.job_instance is not None:
            runtime.job_instance.stop(notify=notify)
        runtime.mark_stopped()

    def stop_job(self, job_name: str) -> JobRuntime:
        self.cleanup_finished_jobs()

        runtime = self.get_runtime(job_name)
        if runtime is None:
            raise RuntimeError(f'Job is not running: {self.get_job_key(job_name)}')

        self._request_runtime_stop(runtime, notify=True)
        return runtime

    def stop_all_jobs(self) -> List[str]:
        self.cleanup_finished_jobs()
        stopped = []

        with self._lock:
            runtimes = list(self._runtimes.values())

        for runtime in runtimes:
            self._request_runtime_stop(runtime, notify=True)
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
                self._request_runtime_stop(runtime, notify=False)
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
            'job_id': runtime.job_id,
            'display_name': runtime.display_name,
            'execution_mode': runtime.execution_mode,
            'worker_name': runtime.worker_name,
            'thread_name': getattr(runtime.thread, 'name', '') if runtime.thread is not None else '',
            'pid': getattr(runtime.process, 'pid', None) if runtime.process is not None else None,
            'is_alive': runtime.is_alive,
            'is_running': runtime.is_running,
            'created_at': runtime.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'stopped_at': runtime.stopped_at.strftime('%Y-%m-%d %H:%M:%S') if runtime.stopped_at else '',
            'status': 'running' if runtime.is_alive and runtime.is_running else 'stopping',
        }
