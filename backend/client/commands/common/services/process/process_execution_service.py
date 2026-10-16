import locale
import os
import signal
import subprocess
import threading
import time

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError


class ProcessExecutionService:
    """
    进程执行基础设施。

    职责：
    - 统一 shell / 流式 / 后台进程启动逻辑
    - 统一取消、超时与强制终止逻辑
    - 从命令层抽离通用子进程基础设施，减少 mixin 内部的基础设施代码量
    """

    def __init__(self, owner):
        self.owner = owner

    def get_default_encoding(self):
        """
        获取系统默认编码
        """
        return locale.getdefaultlocale()[1] or 'utf-8'

    def build_process_creation_kwargs(self) -> dict:
        """
        构造可被强制终止的一组子进程创建参数
        """
        kwargs = {}

        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        else:
            kwargs['start_new_session'] = True

        return kwargs

    def terminate_process(self, process: subprocess.Popen):
        """
        终止子进程；优先杀整个进程组
        """
        if process is None:
            return

        try:
            if process.poll() is not None:
                return
        except Exception:
            return

        try:
            if os.name == 'nt':
                process.kill()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

        try:
            process.wait(timeout=getattr(self.owner, 'PROCESS_KILL_GRACE_SECONDS', 2))
        except Exception:
            pass

    def wait_process_with_cancel_support(self, process: subprocess.Popen, timeout=None):
        effective_timeout = timeout

        while True:
            try:
                self.owner._checkpoint(fallback_timeout=effective_timeout)
                return_code = process.poll()
                if return_code is not None:
                    self.owner._checkpoint(fallback_timeout=effective_timeout)
                    return return_code
                time.sleep(getattr(self.owner, 'PROCESS_WAIT_POLL_INTERVAL', 0.2))
            except CommandCancelledError:
                self.terminate_process(process)
                raise
            except CommandTimeoutError:
                self.terminate_process(process)
                raise subprocess.TimeoutExpired(process.args, effective_timeout)

    def run_shell_command(self, command, timeout=None):
        """
        执行一次性 shell 命令
        """
        encoding = self.get_default_encoding()
        effective_timeout = getattr(self.owner, 'DEFAULT_SHELL_TIMEOUT', None) if timeout is None else timeout

        process = subprocess.Popen(
            command,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            errors='replace',
            **self.build_process_creation_kwargs()
        )
        self.owner._register_cancel_handler(lambda: self.terminate_process(process))

        try:
            while True:
                self.owner._checkpoint(fallback_timeout=effective_timeout)
                try:
                    stdout, stderr = process.communicate(
                        timeout=getattr(self.owner, 'PROCESS_WAIT_POLL_INTERVAL', 0.2)
                    )
                    # A cancel handler can terminate the subprocess between our
                    # polling checkpoint and communicate() returning.
                    self.owner._checkpoint(fallback_timeout=effective_timeout)
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=process.returncode,
                        stdout=stdout,
                        stderr=stderr
                    )
                except subprocess.TimeoutExpired:
                    continue
        except CommandCancelledError:
            self.terminate_process(process)
            raise
        except CommandTimeoutError:
            self.terminate_process(process)
            raise subprocess.TimeoutExpired(process.args, effective_timeout)
        except Exception:
            self.terminate_process(process)
            raise

    def start_stream_process(self, command, *, shell=True, text=False, encoding=None, errors='replace', bufsize=-1):
        """
        启动带流式输出的子进程
        """
        process = subprocess.Popen(
            command,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=text,
            encoding=encoding,
            errors=errors if text else None,
            bufsize=bufsize,
            **self.build_process_creation_kwargs()
        )
        self.owner._register_cancel_handler(lambda: self.terminate_process(process))
        return process

    def stream_process_output(self, stream, status=1, timeout=None):
        """
        持续读取子进程输出流并发送中间结果
        """
        encoding = self.get_default_encoding()

        while True:
            self.owner._checkpoint(fallback_timeout=timeout)
            line = stream.readline()
            if not line:
                break

            if isinstance(line, bytes):
                text = line.decode(encoding, errors='replace').rstrip('\n')
            else:
                text = str(line).rstrip('\n')

            self.owner._send_interim_result(status, text)

    def _start_output_thread(self, stream, status, timeout=None):
        thread = threading.Thread(
            target=self.stream_process_output,
            args=(stream, status, timeout)
        )
        thread.daemon = True
        thread.start()
        return thread

    def start_output_threads(self, process, timeout=None):
        """
        为 stdout/stderr 启动输出读取线程
        """
        stdout_thread = self._start_output_thread(process.stdout, 1, timeout=timeout)
        stderr_thread = self._start_output_thread(process.stderr, 0, timeout=timeout)
        return stdout_thread, stderr_thread

    def wait_stream_process(self, process, timeout=None):
        """
        等待流式子进程结束；超时则强制终止
        """
        effective_timeout = getattr(self.owner, 'DEFAULT_STREAM_TIMEOUT', None) if timeout is None else timeout
        return self.wait_process_with_cancel_support(process, timeout=effective_timeout)

    def spawn_background_process(self, command: str):
        """
        启动后台进程并立即返回
        """
        if os.name == 'nt':
            creation_flags = 0
            for attr_name in ('DETACHED_PROCESS', 'CREATE_NEW_PROCESS_GROUP'):
                creation_flags |= getattr(subprocess, attr_name, 0)

            return subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags
            )

        return subprocess.Popen(
            command,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )








