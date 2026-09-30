import json
import os
import threading
import uuid
from abc import ABC, abstractmethod

from client.http.client_api import ClientApiClient


class Job(ABC):
    """
    后台任务基类。

    每次启动任务时都应创建新的任务实例，
    不要在任务类内部维护单例。
    """

    def __init__(self):
        self.server = None
        self.command_id = None
        self.job_id = str(uuid.uuid4())
        self.job_name = self.__class__.__name__
        self.job_key = ''
        self.is_running = False
        self.stop_event = threading.Event()

        self.client_api = ClientApiClient()
        self.client_id = None
        self.hostname = ''
        self.job_metadata = {}
        self.job_params = {}
        self.execution_mode = 'inproc'

    def bind_context(
        self,
        server,
        command_id,
        client_id=None,
        job_key='',
        job_metadata=None,
        job_params=None,
        execution_mode='inproc',
    ):
        """
        绑定运行上下文
        """
        self.server = server
        self.command_id = command_id
        self.client_id = client_id
        self.job_key = (job_key or '').strip()
        self.hostname = ''
        self.job_metadata = dict(job_metadata or {})
        self.job_params = dict(job_params or {})
        self.execution_mode = str(execution_mode or 'inproc').strip() or 'inproc'
        try:
            self.hostname = (getattr(server, 'info', {}) or {}).get('hostname', '') or ''
        except Exception:
            self.hostname = ''

        self.on_context_bound()

    def on_context_bound(self):
        """
        在 job metadata / params 绑定完成后触发。
        新 job 可在这里消费参数，老 job 不受影响。
        """
        return None

    def get_job_param(self, name: str, default=None):
        return (self.job_params or {}).get(name, default)

    def _build_display_name(self) -> str:
        display_base = self.job_key or self.job_name or 'job'
        return f'{display_base}#{self.job_id[:8]}'

    def _build_report_payload(self, event_type: str, **extra) -> dict:
        worker_name = threading.current_thread().name
        if self.execution_mode == 'subprocess':
            worker_name = f'Process-{os.getpid()}:{worker_name}'

        payload = {
            'event_type': event_type,
            'client_id': self.client_id or '',
            'command_id': self.command_id,
            'job_id': self.job_id,
            'job_name': self.job_name,
            'job_key': self.job_key,
            'display_name': self._build_display_name(),
            'thread_name': worker_name,
            'execution_mode': self.execution_mode,
            'params': dict(self.job_params or {}),
        }
        payload.update(extra)
        return payload

    def _post_job_report(self, payload: dict):
        """
        通过 HTTP 向服务端上报后台任务事件
        """
        if not self.client_id:
            return

        try:
            self.client_api.post_background_job_report(payload, timeout=10)
        except Exception:
            pass

    def send_to_server(self, status, message, eof=0):
        """
        向服务端发送任务输出。
        当前实现改为 HTTP 上报。
        """
        thread_name = threading.current_thread().name
        formatted_message = (
            f'[{self.job_name}#{self.job_id[:8]} @ {thread_name} '
            f'client={self.client_id}] {message}'
        )

        self._post_job_report(
            self._build_report_payload(
                'message',
                status=status,
                text=formatted_message,
                eof=eof,
            )
        )

    def _report_state(self, state: str, status: int = 1, text: str = ''):
        self._post_job_report(
            self._build_report_payload(
                'status',
                state=state,
                status=status,
                text=text,
            )
        )

    def _report_uploaded_file(self, file_info: dict):
        if not isinstance(file_info, dict):
            return

        artifact_id = (file_info.get('artifact_id') or '').strip()
        if not artifact_id:
            return

        self._post_job_report(
            self._build_report_payload(
                'file',
                file={
                    'artifact_id': artifact_id,
                    'artifact_type': file_info.get('artifact_type', ''),
                    'original_name': file_info.get('original_name', ''),
                    'stored_name': file_info.get('stored_name', ''),
                    'relative_path': file_info.get('relative_path', ''),
                    'size': file_info.get('size', 0),
                    'category': file_info.get('category', ''),
                    'hostname': file_info.get('hostname', ''),
                    'client_id': file_info.get('client_id', ''),
                    'download_url': file_info.get('download_url', ''),
                    'raw_url': file_info.get('raw_url', ''),
                    'preview_url': file_info.get('preview_url', ''),
                }
            )
        )

    def _build_upload_form_data(
        self,
        file_path,
        category=None,
        *,
        artifact_type: str = 'files',
        extra: dict | None = None,
    ) -> dict:
        form_data = {
            'artifact_type': (artifact_type or 'files').strip() or 'files',
            'category': (category or '').strip() or 'default',
            'client_id': self.client_id,
            'hostname': self.hostname,
            'job_id': self.job_id,
            'job_name': self.job_name,
            'job_key': self.job_key,
            'source_command_id': self.command_id if self.command_id is not None else '',
        }

        if isinstance(extra, dict) and extra:
            form_data['extra'] = json.dumps(extra, ensure_ascii=False)

        return form_data

    def upload_file_via_http(
        self,
        file_path,
        category=None,
        *,
        artifact_type: str = 'files',
        extra: dict | None = None,
    ):
        form_data = self._build_upload_form_data(
            file_path,
            category=category,
            artifact_type=artifact_type,
            extra=extra,
        )

        response = self.client_api.upload_file(
            file_path,
            form_data,
            timeout=30,
        )

        payload = self.client_api.try_parse_json(response)

        if response.ok and isinstance(payload, dict):
            file_info = payload.get('data') or {}
            if isinstance(file_info, dict):
                self._report_uploaded_file(file_info)

        return response

    def mark_running(self):
        self.is_running = True
        self.stop_event.clear()
        self._report_state('running', status=1, text='Job started')

    def mark_stopped(self):
        self.is_running = False
        self.stop_event.set()
        self._report_state('stopped', status=1, text='Job stopped')

    @abstractmethod
    def run(self):
        raise NotImplementedError

    def request_stop(self, notify: bool = True):
        if self.is_running and notify:
            try:
                self._report_state('stopping', status=1, text='Stop requested')
                self.send_to_server(1, 'Stop requested', 0)
            except Exception:
                pass

        self.is_running = False
        self.stop_event.set()

    def stop(self, notify: bool = True):
        self.request_stop(notify=notify)