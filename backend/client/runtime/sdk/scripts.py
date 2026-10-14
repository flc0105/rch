"""Script SDK: 按 Script Library 名称读取并在当前 Client 内同步执行子脚本。

子脚本沿用调用者的临时 Script Grant，不会自动获得新增权限。
"""
import contextlib
import io
import json
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import PurePosixPath

from client.http.client_api import ClientApiClient
from core.utils.script_metadata import read_script_metadata_from_source, resolve_script_params
from client.runtime.sdk import context


class ScriptSdkScriptsError(RuntimeError):
    pass


_active_scripts = ContextVar("script_sdk_active_script_names", default=())


@dataclass
class ScriptResult:
    name: str
    returncode: int
    stdout: str
    stderr: str = ''

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def text(self) -> str:
        return self.stdout

    def json(self):
        """将被调用脚本 stdout 解析成 JSON；JSON 不合法时明确抛错。"""
        return json.loads(self.stdout)


def _valid_name(name: str) -> str:
    value = str(name or '').strip().replace('\\', '/')
    path = PurePosixPath(value)
    if (not value or value.startswith('/') or value.endswith('/') or
            any(part in ('.', '..') for part in value.split('/')) or
            ':' in value or '?' in value or '#' in value):
        raise ValueError('Invalid script name')
    normalized = str(path)
    if normalized.endswith('.py'):
        normalized = normalized[:-3]
    return normalized


def run(name: str, params: dict | None = None, *, timeout: int = 30) -> ScriptResult:
    """下载 Script Library 脚本并同步执行，返回 stdout/stderr/状态。

    调用方需在 SCRIPT_METADATA['api_grants'] 中声明 'scripts:read'。
    仅在当前 Client 执行，不派发另一条 Server command，不创建新 grant。
    """
    script_name = _valid_name(name)
    if params is not None and not isinstance(params, dict):
        raise ValueError('params must be a dict')
    if not context.get_script_grant_token():
        raise ScriptSdkScriptsError('scripts.run requires SCRIPT_METADATA api_grants: ["scripts:read"]')
    active = _active_scripts.get()
    if script_name == context.script_name() or script_name in active:
        raise ScriptSdkScriptsError(f'Recursive script invocation: {script_name}')
    if len(active) >= 8:
        raise ScriptSdkScriptsError('Nested script invocation limit exceeded')
    code = ClientApiClient().download_text(
        '/api/scripts/download', params={'name': script_name}, timeout=timeout,
    )
    if not code.strip():
        raise ScriptSdkScriptsError(f'Empty script: {script_name}')
    metadata = read_script_metadata_from_source(code, fallback_name=script_name)
    args = resolve_script_params(metadata, params or {})
    script_context = context.get_script_context()
    script_context['script_name'] = script_name
    args['__context__'] = script_context
    namespace = {'__name__': '__main__', '__file__': f'<script:{script_name}>', 'kwargs': args}
    from client.runtime.sdk.context import build_script_sdk_globals, use_script_sdk_context
    namespace.update(build_script_sdk_globals(context.get_command_owner(), args))
    out = io.StringIO()
    err = io.StringIO()
    returncode = 0
    token = _active_scripts.set((*active, script_name))
    try:
        with use_script_sdk_context(context.get_command_owner(), args):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    exec(compile(code, f'<script:{script_name}>', 'exec'), namespace)
                except SystemExit as exc:
                    code_value = exc.code
                    returncode = (code_value if isinstance(code_value, int) else 1) if code_value else 0
                except Exception:
                    import traceback
                    traceback.print_exc()
                    returncode = 1
    finally:
        _active_scripts.reset(token)
    return ScriptResult(script_name, returncode, out.getvalue(), err.getvalue())
