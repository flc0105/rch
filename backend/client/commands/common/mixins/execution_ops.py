import os
import subprocess
import time

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError
from client.commands.runtime.interrupts import interruptible
from client.commands.strategies.python_execution.factory import (
    build_python_execution_strategy,
    get_python_execution_mode
)
from client.commands.common.services.process.process_execution_service import ProcessExecutionService
from client.config.runtime_config import (
    COMMAND_DEFAULT_SHELL_TIMEOUT,
    COMMAND_DEFAULT_STREAM_TIMEOUT,
)
from core.utils.decorator import desc


class CommandExecutionMixin:
    """
    shell-like / Python script 执行命令。

    这里只保留执行相关逻辑：
    - shell
    - spawn
    - read
    - pyexec_collect
    - pyexec_stream
    - execute_script_stream

    session 控制已拆到 session_ops.py
    system/network 命令已拆到 system_ops.py
    """

    DEFAULT_SHELL_TIMEOUT = COMMAND_DEFAULT_SHELL_TIMEOUT
    DEFAULT_STREAM_TIMEOUT = COMMAND_DEFAULT_STREAM_TIMEOUT
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

    def _merge_script_kwargs_with_context(self, kwargs=None):
        merged = dict(kwargs or {})
        script_grant = merged.pop('__script_grant__', None)
        script_name = merged.pop('__script_name__', None)
        merged.pop('__script_grant_request__', None)

        context = self._build_script_context()
        if script_name:
            context['script_name'] = str(script_name or '').strip()
        if isinstance(script_grant, dict) and script_grant:
            context['script_grant'] = script_grant
        merged['__context__'] = context
        return merged

    def _execute_python_collect(self, code, kwargs=None, mode: str = '', default_mode: str = 'inproc'):
        strategy = self._get_python_execution_strategy(mode=mode, default_mode=default_mode)
        return strategy.execute_collect(
            code,
            kwargs=self._merge_script_kwargs_with_context(kwargs),
            timeout=self.DEFAULT_STREAM_TIMEOUT,
        )

    def _execute_python_stream(self, code, kwargs=None, mode: str = '', default_mode: str = 'inproc'):
        strategy = self._get_python_execution_strategy(mode=mode, default_mode=default_mode)
        return strategy.execute_stream(
            code,
            kwargs=kwargs,
            timeout=self.DEFAULT_STREAM_TIMEOUT,
        )

    def execute_script_stream(self, code, kwargs=None):
        """
        script 内部执行入口：
        - 对外不单独作为推荐命令暴露
        - 默认只走 stream
        - 当前进程 / 子进程由 script strategy 决定
        """
        return self._execute_python_collect(
            code,
            kwargs=kwargs,
            mode=get_python_execution_mode(),
            default_mode='inproc',
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

    # ------------------ 基础执行命令 ------------------ #
    @desc('Change working directory', group='shell')
    @interruptible()
    def cd(self, path):
        try:
            if not path.strip():
                return 1, os.getcwd()
            os.chdir(path)
            return 1, ""
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to change directory: {e}'

    @desc('Run a shell command', group='shell')
    @interruptible()
    def shell(self, command):
        try:
            result = self._run_shell_command(command)
            if result.returncode == 0:
                return 1, result.stdout
            return 0, result.stderr or f'Command exited with code {result.returncode}'
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to execute command: {e}'

    @desc('Run a program in background', group='shell')
    @interruptible()
    def spawn(self, command):
        """
        后台启动指定程序/命令，不等待其执行结束。
        """
        command_text = (command or '').strip()
        if not command_text:
            return 0, 'Usage: spawn <program ...>'

        try:
            process = self._spawn_background_process(command_text)
            return 1, (
                f'Background process started\n'
                f'PID: {process.pid}\n'
                f'Command: {command_text}'
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to start background process: {e}'

    @desc('Run a command with live output', group='shell')
    @interruptible()
    def read(self, command):
        try:
            process = self._start_stream_process(command)
            self._start_output_threads(process)
            self._wait_stream_process(process)
            time.sleep(0.1)

            if process.returncode == 0:
                self._send_final_result(1, "Command completed")
            else:
                self._send_final_result(0, f'Command exited with code {process.returncode}')
        except CommandCancelledError:
            self._send_final_result(0, 'Command cancelled')
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            self._send_final_result(0, 'Command timed out and was terminated')
        except Exception as e:
            self._send_final_result(0, f'Failed to execute command: {e}')

    @desc('Execute Python code and collect output', group='shell')
    @interruptible()
    def pyexec_collect(self, code, kwargs=None):
        """
        一次性返回版本。
        """
        try:
            return self._execute_python_collect(
                code,
                kwargs=kwargs,
                mode=get_python_execution_mode(),
                default_mode='inproc',
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            return 0, 'Command timed out'
        except Exception as e:
            return 0, f'Failed to execute code: {e}'

    @desc('Execute Python code with streaming output', group='shell')
    @interruptible()
    def pyexec_stream(self, code, kwargs=None):
        """
        流式返回版本。
        """
        try:
            return self._execute_python_stream(
                code,
                kwargs=kwargs,
                mode=get_python_execution_mode(),
                default_mode='inproc',
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            return 0, 'Command timed out'
        except Exception as e:
            return 0, f'Failed to execute code: {e}'