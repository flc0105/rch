import os
import subprocess
import time

from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.execution.python_execution.factory import (
    build_python_execution_strategy
)
from client.runtime.execution.process.process_execution_service import ProcessExecutionService
from client.config import runtime_config


class PythonProcessExecutionMixin:
    """Shared Python and process execution capabilities."""
    @property
    def DEFAULT_SHELL_TIMEOUT(self):
        return runtime_config.COMMAND_DEFAULT_SHELL_TIMEOUT

    @property
    def DEFAULT_STREAM_TIMEOUT(self):
        return runtime_config.COMMAND_DEFAULT_STREAM_TIMEOUT

    PROCESS_KILL_GRACE_SECONDS = 2
    # 固定子进程等待轮询间隔，不再作为 runtime_config 暴露。
    PROCESS_WAIT_POLL_INTERVAL = 0.2

    def __init__(self, *args, **kwargs):
        self._process_execution_service = None
        self._python_execution_strategy_cache = {}
        super().__init__(*args, **kwargs)

    # ------------------ Python 执行策略 ------------------ #
    def _get_python_execution_strategy(self, mode: str = '', default_mode: str = 'inproc'):
        cache_key = f'{mode or ""}::{default_mode or ""}'
        if cache_key not in self._python_execution_strategy_cache:
            self._python_execution_strategy_cache[cache_key] = build_python_execution_strategy(
                self,
                mode=mode,
                default_mode=default_mode,
            )
        return self._python_execution_strategy_cache[cache_key]

    def _build_script_context(self):
        # 给脚本注入统一上下文，避免和平铺业务参数重名
        context = {}
        socket_obj = getattr(self, 'socket', None)
        context['client_id'] = getattr(socket_obj, 'client_id', '') or ''
        context['command_id'] = self.command_id if self.command_id is not None else ''
        try:
            from client.runtime.client_util import get_system_paths
            from core.device.local_identity import get_local_identity

            identity = get_local_identity()
            context['hostname'] = identity.hostname
            context['machine_id'] = identity.machine_id
            context['platform'] = identity.os_alias
            context['os_alias'] = identity.os_alias
            context['os_type'] = identity.os_type
            context['os_ver'] = identity.os_version
            context['arch'] = identity.arch
            context['system_paths'] = get_system_paths()
        except Exception:
            pass
        return context


    # def _merge_script_kwargs_with_context(self, kwargs=None):
    #     merged = dict(kwargs or {})
    #     merged['__context__'] = self._build_script_context()
    #     return merged

    def _merge_script_kwargs_with_context(self, kwargs=None, script_name=None):
        merged = dict(kwargs or {})

        context = self._build_script_context()
        if script_name:
            context['script_name'] = str(script_name or '').strip()
        socket = getattr(self, 'socket', None)
        context['client_session_token'] = str(getattr(socket, 'client_session_token', '') or '')
        merged['__context__'] = context
        return merged

    def _execute_python_collect(self, code, kwargs=None, mode: str = '', default_mode: str = 'inproc', timeout=None, script_name=None):
        strategy = self._get_python_execution_strategy(mode=mode, default_mode=default_mode)
        return strategy.execute_collect(
            code,
            kwargs=self._merge_script_kwargs_with_context(kwargs, script_name=script_name),
            timeout=self.DEFAULT_STREAM_TIMEOUT if timeout is None else timeout,
        )

    def _execute_python_stream(self, code, kwargs=None, mode: str = '', default_mode: str = 'inproc', timeout=None, script_name=None):
        strategy = self._get_python_execution_strategy(mode=mode, default_mode=default_mode)
        return strategy.execute_stream(
            code,
            kwargs=self._merge_script_kwargs_with_context(kwargs, script_name=script_name),
            timeout=self.DEFAULT_STREAM_TIMEOUT if timeout is None else timeout,
        )

    # ------------------ 进程执行服务 ------------------ #
    def _get_process_execution_service(self):
        if self._process_execution_service is None:
            self._process_execution_service = ProcessExecutionService(self)
        return self._process_execution_service

    # ------------------ 通用输出/子进程工具 ------------------ #
    def _get_default_encoding(self):
        """
        获取系统默认编码
        """
        return self._get_process_execution_service().get_default_encoding()

    def _stream_process_output(self, stream, status=1):
        """
        持续读取子进程输出流并发送中间结果
        """
        return self._get_process_execution_service().stream_process_output(
            stream,
            status=status,
            timeout=self.DEFAULT_STREAM_TIMEOUT,
        )

    def _build_process_creation_kwargs(self) -> dict:
        """
        构造可被强制终止的一组子进程创建参数
        """
        return self._get_process_execution_service().build_process_creation_kwargs()

    def _terminate_process(self, process: subprocess.Popen):
        """
        终止子进程；优先杀整个进程组
        """
        return self._get_process_execution_service().terminate_process(process)

    def _wait_process_with_cancel_support(self, process: subprocess.Popen, timeout=None):
        return self._get_process_execution_service().wait_process_with_cancel_support(
            process,
            timeout=timeout,
        )

    def _run_shell_command(self, command, timeout=None):
        """
        执行一次性 shell 命令
        """
        return self._get_process_execution_service().run_shell_command(
            command,
            timeout=timeout,
        )

    def _start_stream_process(self, command):
        """
        启动带流式输出的子进程
        """
        return self._get_process_execution_service().start_stream_process(command)

    def _start_output_threads(self, process):
        """
        为 stdout/stderr 启动输出读取线程
        """
        return self._get_process_execution_service().start_output_threads(
            process,
            timeout=self.DEFAULT_STREAM_TIMEOUT,
        )

    def _wait_stream_process(self, process, timeout=None):
        """
        等待流式子进程结束；超时则强制终止
        """
        effective_timeout = self.DEFAULT_STREAM_TIMEOUT if timeout is None else timeout
        return self._get_process_execution_service().wait_stream_process(
            process,
            timeout=effective_timeout,
        )

    def _spawn_background_process(self, command: str):
        """
        启动后台进程并立即返回
        """
        return self._get_process_execution_service().spawn_background_process(command)

    def _spawn_detached_program(self, command: str):
        return self._get_process_execution_service().spawn_detached_program(command)

