import inspect
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from client.runtime.sdk.context import get_execution_owner


@dataclass(frozen=True)
class ScriptCommandAccess:
    names: Callable[[], list[str]]
    resolve: Callable[[Any, str], Any]


class ScriptSdkCommandError(RuntimeError):
    """Script SDK command 统一异常。"""
    pass


@dataclass(frozen=True)
class ShellResult:
    command: str
    returncode: int
    stdout: str = ''
    stderr: str = ''

    @property
    def ok(self) -> bool:
        return int(self.returncode or 0) == 0

    @property
    def text(self) -> str:
        return self.stdout if self.stdout else self.stderr

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class BackgroundProcess:
    command: str
    pid: int

    def __str__(self) -> str:
        return f'PID {self.pid}: {self.command}'


@dataclass(frozen=True)
class ClientCommandResult:
    name: str
    status: int
    output: Any = ''

    @property
    def ok(self) -> bool:
        return int(self.status or 0) == 1

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        return '' if self.output is None else str(self.output)


def _safe_text(value) -> str:
    return '' if value is None else str(value).strip()


def _normalize_shell_completed(command: str, completed) -> ShellResult:
    return ShellResult(
        command=command,
        returncode=int(getattr(completed, 'returncode', 1) or 0),
        stdout=getattr(completed, 'stdout', '') or '',
        stderr=getattr(completed, 'stderr', '') or '',
    )


def _spawn_background_with_subprocess(command_text: str) -> subprocess.Popen:
    if os.name == 'nt':
        creation_flags = 0
        for attr_name in ('DETACHED_PROCESS', 'CREATE_NEW_PROCESS_GROUP'):
            creation_flags |= getattr(subprocess, attr_name, 0)
        return subprocess.Popen(
            command_text,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

    return subprocess.Popen(
        command_text,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def run_shell(command: str, *, wait: bool = True, background: bool = False,
              mode: str = '', stream: bool = False, timeout=None):
    """
    执行 shell 命令。

    用法：
        result = command.run_shell('whoami')
        proc = command.run_shell('python app.py', background=True)
        proc = command.run_shell('python app.py', wait=False)
    """
    command_text = _safe_text(command)
    if not command_text:
        raise ValueError('command is required')

    normalized_mode = _safe_text(mode).lower()
    run_in_background = bool(background) or wait is False or normalized_mode in {'background', 'bg', 'detach'}
    owner = get_execution_owner()

    if run_in_background:
        if owner is not None and hasattr(owner, '_spawn_background_process'):
            process = owner._spawn_background_process(command_text)
        else:
            process = _spawn_background_with_subprocess(command_text)
        return BackgroundProcess(command=command_text, pid=int(getattr(process, 'pid', 0) or 0))

    if stream and owner is not None and hasattr(owner, '_start_stream_process'):
        process = owner._start_stream_process(command_text)
        owner._start_output_threads(process)
        owner._wait_stream_process(process, timeout=timeout)
        return ShellResult(command=command_text, returncode=int(process.returncode or 0))

    if owner is not None and hasattr(owner, '_run_shell_command'):
        completed = owner._run_shell_command(command_text, timeout=timeout)
        return _normalize_shell_completed(command_text, completed)

    completed = subprocess.run(
        command_text,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return _normalize_shell_completed(command_text, completed)


def run_background(command: str):
    return run_shell(command, background=True)


def stream_shell(command: str, *, timeout=None):
    return run_shell(command, stream=True, timeout=timeout)


def _resolve_client_command(owner, name: str):
    command_name = _safe_text(name)
    if not command_name:
        raise ValueError('client command name is required')
    if owner is None:
        raise ScriptSdkCommandError('client command SDK requires inproc Python execution mode')
    resolver = getattr(owner, "resolve_sdk_command", None)
    if callable(resolver):
        func = resolver(command_name)
        if func is None:
            raise ScriptSdkCommandError(f"Client command is not exported: {command_name}")
        return command_name, func
    if not hasattr(owner, command_name):
        raise ScriptSdkCommandError(f'Client command not found: {command_name}')

    func = getattr(owner, command_name)
    if not callable(func) or not hasattr(func, 'help'):
        raise ScriptSdkCommandError(f'Client command is not exported: {command_name}')
    return command_name, func


def _invoke_client_command(func, args, kwargs):
    if args or kwargs:
        return func(*args, **kwargs)

    params = inspect.signature(func).parameters
    if len(params) == 0:
        return func()
    return func('')


def _normalize_client_result(name: str, result) -> ClientCommandResult:
    if isinstance(result, tuple) and len(result) >= 2:
        return ClientCommandResult(name=name, status=int(result[0] or 0), output=result[1])
    if result is None:
        return ClientCommandResult(name=name, status=1, output='')
    return ClientCommandResult(name=name, status=1, output=result)


def run_client(name: str, *args, **kwargs) -> ClientCommandResult:
    """
    直接调用当前 client 已导出的命令方法。

    用法：
        info = command.run_client('getinfo')
        shot = command.screenshot()
    """
    command_name, func = _resolve_client_command(get_execution_owner(), name)
    return _normalize_client_result(command_name, _invoke_client_command(func, args, kwargs))


def build_client_command_function(name: str):
    command_name = _safe_text(name)

    def _sdk_client_command(*args, **kwargs):
        return run_client(command_name, *args, **kwargs)

    _sdk_client_command.__name__ = command_name or 'client_command'
    _sdk_client_command.__doc__ = f'Script SDK wrapper for client command: {command_name}'
    return _sdk_client_command


def __getattr__(name: str):
    if name.startswith('_'):
        raise AttributeError(name)
    return build_client_command_function(name)
