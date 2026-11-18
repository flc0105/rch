from client.runtime.http_transfer.http_file_transfer_service import HttpFileTransferService
from client.runtime.filesystem.archive_service import ArchiveService
from client.runtime.filesystem.file_system_service import FileSystemService
from client.runtime.filesystem.path_resolver import PathResolver
from core.protocol.structured_arg_codec import StructuredArgCodec
from client.http.client_api import ClientApiClient
from client.config import runtime_config

class ExecutionResultMixin:
    """Typed execution events shared by shell, Control and Script producers."""

    def emit_progress(self, message: str, *, level: str | None = None):
        event = {'event_type': 'progress', 'message': str(message)}
        if level is not None:
            event['level'] = level
        self.socket.send_event(self.command_id, event)

    def emit_chunk(self, message: str = '', *, data=None):
        event = {'event_type': 'chunk'}
        if data is not None:
            event['data'] = data
            if message:
                event['message'] = str(message)
        else:
            event['message'] = str(message)
        self.socket.send_event(self.command_id, event)

    def emit_completed(self, *, status: str = 'success', message: str = '',
                       data=None, references=None):
        from core.protocol.result_envelope import ResultEnvelope
        self.socket.send_event(self.command_id, ResultEnvelope(
            status=status, message=str(message), data=data,
            references=references,
        ).as_payload())


class ExecutionRuntimeMixin:
    """
    执行运行时能力：
    - 负责 cancel / timeout / cleanup / checkpoint 相关基础设施
    - 不负责协议层输出
    """

    def _get_execution_context(self):
        return self.execution_context

    def _is_cancel_requested(self) -> bool:
        context = self._get_execution_context()
        return bool(context and context.is_cancel_requested())

    def _resolve_timeout(self, fallback_timeout=None):
        context = self._get_execution_context()
        effective_fallback = self._resolve_command_fallback_timeout(fallback_timeout)
        if context is None:
            return effective_fallback
        return context.resolve_timeout(effective_fallback)

    def _resolve_command_fallback_timeout(self, fallback_timeout=None):
        # 显式传入的 fallback 优先，例如 shell / stream / HTTP 自己的 timeout。
        # COMMAND_DEFAULT_TIMEOUT 只作为没有专用 timeout 时的通用兜底。
        if fallback_timeout is not None:
            return fallback_timeout
        return runtime_config.COMMAND_DEFAULT_TIMEOUT

    def _ensure_not_cancelled(self):
        context = self._get_execution_context()
        if context is None:
            return
        context.raise_if_cancelled()

    def _ensure_not_timed_out(self, fallback_timeout=None):
        context = self._get_execution_context()
        if context is None:
            return
        context.raise_if_timed_out(
            fallback_timeout=self._resolve_command_fallback_timeout(fallback_timeout)
        )

    def _checkpoint(self, fallback_timeout=None):
        context = self._get_execution_context()
        if context is None:
            return
        context.raise_if_interrupted(
            fallback_timeout=self._resolve_command_fallback_timeout(fallback_timeout)
        )

    def _set_cancel_policy(self, mode: str = 'none', message: str = ''):
        context = self._get_execution_context()
        if context is None:
            return
        context.set_cancel_policy(mode=mode, message=message)

    def _set_timeout(self, timeout: float):
        """
        设置当前命令的超时时间
        """
        context = self._get_execution_context()
        if context is None:
            return
        context.set_timeout(timeout)

    def _register_cancel_handler(self, handler):
        context = self._get_execution_context()
        if context is None:
            return
        context.add_cancel_handler(handler)

    def _register_cleanup_handler(self, handler):
        context = self._get_execution_context()
        if context is None:
            return
        context.add_cleanup_handler(handler)

    def _cleanup_execution_context(self):
        context = self._get_execution_context()
        if context is None:
            return
        context.run_cleanup()

    def _run_checked(self, func, *args, fallback_timeout=None, **kwargs):
        self._checkpoint(fallback_timeout=fallback_timeout)
        return func(*args, **kwargs)

    def _iter_checked(self, iterable, fallback_timeout=None, check_interval: int = 1):
        interval = max(int(check_interval or 1), 1)
        for index, item in enumerate(iterable, start=1):
            if index == 1 or index % interval == 0:
                self._checkpoint(fallback_timeout=fallback_timeout)
            yield item
        self._checkpoint(fallback_timeout=fallback_timeout)

    def _read_checked(self, file_obj, size=-1, fallback_timeout=None):
        self._checkpoint(fallback_timeout=fallback_timeout)
        return file_obj.read(size)

    def _write_checked(self, file_obj, data, fallback_timeout=None):
        self._checkpoint(fallback_timeout=fallback_timeout)
        return file_obj.write(data)


class ExecutionResources:
    """Lazy per-execution runtime capabilities used by Commands and Scripts."""

    @property
    def DEFAULT_SHELL_TIMEOUT(self):
        return runtime_config.COMMAND_DEFAULT_SHELL_TIMEOUT

    @property
    def DEFAULT_STREAM_TIMEOUT(self):
        return runtime_config.COMMAND_DEFAULT_STREAM_TIMEOUT

    @property
    def process_execution_service(self):
        from client.runtime.execution.process.process_execution_service import ProcessExecutionService
        service = getattr(self, '_process_execution_service', None)
        if service is None:
            service = ProcessExecutionService(self)
            self._process_execution_service = service
        return service

    @property
    def python_execution_service(self):
        from client.runtime.execution.python_execution.service import PythonExecutionService
        service = getattr(self, '_python_execution_service', None)
        if service is None:
            service = PythonExecutionService(self)
            self._python_execution_service = service
        return service
    @property
    def http_file_transfer_service(self):
        service = getattr(self, '_http_file_transfer_service', None)
        if service is None:
            service = HttpFileTransferService(
                self,
                archive_service=self.archive_service,
                client_api=self.client_api,
            )
            self._http_file_transfer_service = service
        return service

    @property
    def structured_arg_codec(self):
        service = getattr(self, '_structured_arg_codec', None)
        if service is None:
            service = StructuredArgCodec()
            self._structured_arg_codec = service
        return service

    @property
    def path_resolver(self):
        service = getattr(self, '_path_resolver', None)
        if service is None:
            service = PathResolver(
                codec=self.structured_arg_codec,
                iter_checked=self._iter_checked,
            )
            self._path_resolver = service
        return service

    @property
    def file_system_service(self):
        service = getattr(self, '_file_system_service', None)
        if service is None:
            service = FileSystemService(
                path_resolver=self.path_resolver,
                run_checked=self._run_checked,
                iter_checked=self._iter_checked,
            )
            self._file_system_service = service
        return service

    @property
    def archive_service(self):
        service = getattr(self, '_archive_service', None)
        if service is None:
            service = ArchiveService(
                path_resolver=self.path_resolver,
                checkpoint=self._checkpoint,
                iter_checked=self._iter_checked,
            )
            self._archive_service = service
        return service

    @property
    def client_api(self):
        service = getattr(self, '_client_api', None)
        if service is None:
            service = ClientApiClient()
            self._client_api = service
        return service

class ExecutionScope(ExecutionResultMixin, ExecutionRuntimeMixin, ExecutionResources):
    """Capabilities bound to one execution, independent of any command catalog."""

    def __init__(self, socket, context):
        self.socket = socket
        self.command_id = context.command_id
        self.execution_context = context

