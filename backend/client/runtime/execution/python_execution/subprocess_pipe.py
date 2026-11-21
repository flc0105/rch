import base64
import json
import secrets
import socket
import os
import pickle
import subprocess
import sys
import threading
import tempfile

from client.runtime.execution.python_execution.output import StreamOutput
from client.runtime.execution.python_execution.event_channel import read_event_stream
from core.utils.command_output import ResultEventType

from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.execution.python_execution.base import PythonExecutionStrategy


class SubprocessPipePythonExecutionStrategy(PythonExecutionStrategy):
    MODE_NAME = 'subprocess_pipe'

    def is_cancel_supported(self) -> bool:
        return True

    def _serialize_kwargs(self, kwargs) -> str:
        if kwargs is None:
            kwargs = {}
        payload = pickle.dumps(kwargs)
        return base64.b64encode(payload).decode('ascii')

    def _build_bootstrap_script(self, code, kwargs=None, event_endpoint=None) -> str:
        """
        这里保留 bootstrap 概念，但不落地临时文件。
        它只负责把用户代码和 kwargs 包成一段完整的 Python 文本，
        然后直接通过 stdin 管道喂给子进程。
        """
        from types import SimpleNamespace
        from client.runtime.command_variable_resolver import CommandVariableResolver

        payload = dict(kwargs or {})
        script_context = dict(payload.get('__context__') or {})
        resolver = CommandVariableResolver(SimpleNamespace(client_id=script_context.get('client_id', '')))
        # 子进程的 argv / PID 与 Client 不同，先保存 Client 本体的取值。
        script_context['__rch_variables__'] = {
            name: resolver.resolve('${rch:' + name + '}', command_id=script_context.get('command_id'))
            for name in ('exec_path', 'launch_command', 'runtime', 'pid', 'client_id', 'command_id')
        }
        payload['__context__'] = script_context
        kwargs_payload = self._serialize_kwargs(payload)

        return f"""import base64
import pickle
import traceback

from client.runtime.sdk.context import build_script_sdk_globals, use_script_sdk_context
from client.runtime.execution.python_execution.event_channel import connect_event_stream

OUTPUT_ENDPOINT = {event_endpoint!r}
USER_CODE = {code!r}
KWARGS_PAYLOAD = {kwargs_payload!r}

try:
    kwargs = pickle.loads(base64.b64decode(KWARGS_PAYLOAD.encode('ascii')))
except Exception:
    kwargs = {{}}

exec_globals = {{'__name__': '__main__'}}
exec_globals.update(kwargs)
exec_globals.update(build_script_sdk_globals(None, kwargs))
exec_globals['kwargs'] = kwargs

try:
    with connect_event_stream(OUTPUT_ENDPOINT) as emit_event:
        try:
            with use_script_sdk_context(None, kwargs, emit_event=emit_event):
                exec(compile(USER_CODE, '<remote_pyexec>', 'exec'), exec_globals)
        except BaseException:
            # Even sys.exit(0) from user code is a script failure.
            traceback.print_exc()
            raise SystemExit(1)
except Exception:
    traceback.print_exc()
    raise SystemExit(1)
"""

    def _start_python_process(self):
        process = subprocess.Popen(
            [sys.executable, '-u', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            **self.owner.process_execution_service.build_process_creation_kwargs()
        )
        self.owner._register_cancel_handler(lambda: self.owner.process_execution_service.terminate_process(process))
        return process

    def _execute(self, code, kwargs, timeout, emit=None):
        self.configure_context()
        # Both text and structured events cross one authenticated loopback socket.
        # stdout only captures interpreter/bootstrap errors before channel setup.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            token = secrets.token_urlsafe(32)
            endpoint = {'port': listener.getsockname()[1], 'token': token}
            bootstrap = self._build_bootstrap_script(code, kwargs=kwargs, event_endpoint=endpoint).encode('utf-8')
            process = self._start_python_process()
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+t', encoding='utf-8', newline='') as collected, \
                 tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+t', encoding='utf-8', newline='') as events:
                errors = []
                output_lock = threading.RLock()
                has_structured = [False]
                def emit_text(text):
                    if emit is not None:
                        emit(text)
                    else:
                        events.write(json.dumps({'kind': 'text', 'text': text}, ensure_ascii=False) + '\n')
                output = StreamOutput(emit_text)

                def consume(event):
                    with output_lock:
                        if event['kind'] == 'progress':
                            # Explicit progress is immediate even in collect mode.
                            # It is not stdout and must never change final status.
                            from core.utils.output_marker import OUTPUT_MARKERS
                            message = event.get('message')
                            level = event.get('level')
                            if not isinstance(message, str) or (level is not None and level not in OUTPUT_MARKERS):
                                raise ValueError('Invalid Python progress event')
                            output.flush()
                            self.owner.emit_progress(message, level=level)
                        elif event['kind'] == 'text':
                            value = event['text']
                            if not isinstance(value, str):
                                raise ValueError('Invalid Python text event')
                            if emit is None:
                                collected.write(value)
                            output.write(value)
                        else:
                            if not isinstance(event.get('data'), (dict, list)):
                                raise ValueError('Invalid structured Python output')
                            output.flush()
                            has_structured[0] = True
                            payload = {'event_type': ResultEventType.CHUNK,
                                       'data': event['data']}
                            if 'view' in event:
                                from core.protocol.result_envelope import build_result_wire_event
                                build_result_wire_event('script', {**payload, 'view': event['view']})
                                payload['view'] = event['view']
                            if emit is None:
                                events.write(json.dumps({'kind': 'data', 'data': payload}, ensure_ascii=False) + '\n')
                            else:
                                self.owner.emit_chunk(data=payload['data'], view=payload.get('view'))

                def read_events():
                    try:
                        read_event_stream(listener, process, token, consume)
                    except Exception as exc:
                        errors.append(exc)

                def read_output():
                    try:
                        with process.stdout as reader:
                            import codecs
                            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
                            while True:
                                data = reader.read(16384)
                                if not data:
                                    break
                                consume({'kind': 'text', 'text': decoder.decode(data)})
                            tail = decoder.decode(b'', final=True)
                            if tail:
                                consume({'kind': 'text', 'text': tail})
                    except Exception as exc:
                        errors.append(exc)

                def write_input():
                    try:
                        with process.stdin as pipe:
                            view = memoryview(bootstrap)
                            while view:
                                count = pipe.write(view)
                                if not count:
                                    break
                                view = view[count:]
                    except BrokenPipeError:
                        pass
                    except Exception as exc:
                        errors.append(exc)

                reader = threading.Thread(target=read_output, daemon=True)
                channel = threading.Thread(target=read_events, daemon=True)
                writer = threading.Thread(target=write_input, daemon=True)
                reader.start()
                channel.start()
                writer.start()
                status, message = 1, ''
                interruption = None
                try:
                    self.owner.process_execution_service.wait_process_with_cancel_support(process, timeout=timeout)
                    while reader.is_alive() or writer.is_alive() or channel.is_alive():
                        self.owner._checkpoint(fallback_timeout=timeout)
                        reader.join(0.05)
                        writer.join(0.05)
                        channel.join(0.05)
                    self.owner._checkpoint(fallback_timeout=timeout)
                    process.wait()
                    if errors:
                        status, message = 0, f'Failed to read/write Python process: {errors[0]}'
                    elif process.returncode:
                        status, message = 0, f'Process exited with code {process.returncode}'
                except CommandCancelledError as exc:
                    interruption = exc
                except (CommandTimeoutError, subprocess.TimeoutExpired):
                    interruption = CommandTimeoutError(f'Python execution timed out after {timeout} seconds')
                except Exception as exc:
                    status, message = 0, f'Failed to execute code: {exc}'
                finally:
                    if process.poll() is None:
                        self.owner.process_execution_service.terminate_process(process)
                    if interruption is not None:
                        self.owner.process_execution_service.terminate_process_group(process)
                    writer.join(2)
                    reader.join(2)
                    channel.join(2)
                    with output_lock:
                        output.flush()
                    if reader.is_alive() or channel.is_alive():
                        self.owner.process_execution_service.terminate_process_group(process)
                        status, message = 0, message or 'Python output channel did not close'
                if interruption is not None:
                    collected.seek(0)
                    interruption.output = collected.read() if emit is None else ''
                    raise interruption
                if emit is not None:
                    return status, message or 'Code execution completed'
                if has_structured[0]:
                    events.seek(0)
                    for line in events:
                        item = json.loads(line)
                        if item['kind'] == 'data':
                            self.owner.emit_chunk(data=item['data']['data'], view=item['data'].get('view'))
                        else:
                            self.owner.emit_chunk(item['text'])
                    return status, message or 'Code execution completed'
                collected.seek(0)
                text = collected.read()
                return status, text + (('\n' if text and not text.endswith('\n') else '') + message if message else '')

    def execute_collect(self, code, kwargs=None, timeout=None):
        return self._execute(code, kwargs, timeout)

    def execute_stream(self, code, kwargs=None, timeout=None):
        return self._execute(code, kwargs, timeout, lambda text: self.owner.emit_chunk(text))

