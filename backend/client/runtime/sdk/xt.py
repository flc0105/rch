import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any
from client.runtime.sdk import context
from client.runtime.sdk.context import get_command_owner
from core.external_tools.paths import EXTERNAL_TOOLS_INSTALL_ROOT, EXTERNAL_TOOLS_RUNTIME_ROOT
from core.external_tools.payload import client_exec_payload
from core.platform.normalization import normalize_arch, normalize_platform
from core.external_tools.selector import (
    package_arch_matches,
    package_platform_matches,
    resolve_exec_rel_path,
    select_package_key,
)
from core.external_tools.template import render_value


EXTERNAL_TOOLS_CATALOG_GRANT = 'external_tools:catalog'


class ScriptSdkExternalToolError(RuntimeError):
    """Script SDK external tool 统一异常。"""
    pass


@dataclass(frozen=True)
class ExternalToolExecResult:
    exec_name: str
    command: list[str]
    returncode: int
    stdout: str = ''
    stderr: str = ''
    executable: str = ''

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


class ExternalToolHandle:
    """当前 client 上的一个 external tool exec 句柄。"""

    def __init__(self, exec_name: str):
        self.exec_name = _require_exec_name(exec_name)

    @property
    def is_installed(self) -> bool:
        return bool(_install_status(self.exec_name).get('installed'))

    def status(self) -> dict:
        return _install_status(self.exec_name)

    def which(self) -> str:
        payload = _build_exec_payload(self.exec_name)
        try:
            return _external_tool_service().which_payload(payload)
        except FileNotFoundError as exc:
            raise _not_installed_error(self.exec_name, str(exc)) from None
        except Exception as exc:
            raise ScriptSdkExternalToolError(str(exc) or f'Failed to resolve external tool: {self.exec_name}') from exc

    def __call__(self, raw_args: Any = '', *, timeout=None, cwd: str = '') -> ExternalToolExecResult:
        return run(self.exec_name, raw_args=raw_args, timeout=timeout, cwd=cwd)

    def __repr__(self) -> str:
        return f"ExternalToolHandle(exec_name={self.exec_name!r})"


def _safe_text(value) -> str:
    return '' if value is None else str(value).strip()


def _require_exec_name(value) -> str:
    text = _safe_text(value)
    if not text:
        raise ValueError('external tool exec name is required')
    return text


def _missing_grant_message() -> str:
    return (
        f'External tool SDK requires script grant: {EXTERNAL_TOOLS_CATALOG_GRANT}. '
        f'Add SCRIPT_METADATA["api_grants"] = ["{EXTERNAL_TOOLS_CATALOG_GRANT}"] to this script.'
    )


def _target_platform() -> str:
    value = normalize_platform(context.platform())
    if not value:
        raise ScriptSdkExternalToolError('current platform is empty')
    return value


def _target_arch() -> str:
    value = normalize_arch(context.arch())
    if not value:
        raise ScriptSdkExternalToolError('current arch is empty')
    return value


def _external_tool_service():
    owner = get_command_owner()
    service = getattr(owner, 'external_tool_service', None) if owner is not None else None
    if service is None:
        raise ScriptSdkExternalToolError('external tool SDK requires inproc Python execution mode')
    return service


def _build_catalog_request_payload() -> dict:
    return {
        'platform': _target_platform(),
        'arch': _target_arch(),
    }


def _load_client_catalog() -> dict:
    try:
        from client.http.client_api import ClientApiClient, ClientApiError

        # Script SDK 运行在当前 client 内部，不能再请求 server 向当前 client 下发
        # external_tool_install_statuses 命令，否则会因为当前 run_script 正在执行而触发 busy。
        # 这里仅读取服务端 catalog 元数据，安装状态由当前进程本地 external_tool_service 计算。
        data = ClientApiClient().get_data(
            '/api/external-tools/catalog',
            timeout=30,
        )
    except ImportError as exc:
        raise ScriptSdkExternalToolError('client.http.client_api is required to load external tool catalog') from exc
    except ClientApiError as exc:
        message = str(exc) or 'Failed to load external tool catalog'
        if message in {'Authentication required', 'Forbidden'}:
            raise ScriptSdkExternalToolError(_missing_grant_message()) from None
        raise ScriptSdkExternalToolError(message) from None
    except Exception as exc:
        raise ScriptSdkExternalToolError(str(exc) or 'Failed to load external tool catalog') from exc

    if not isinstance(data, dict):
        raise ScriptSdkExternalToolError('Invalid external tool catalog response')
    return data


def _iter_packages():
    catalog = _load_client_catalog()
    for item in catalog.get('items') or []:
        if isinstance(item, dict) and not item.get('error'):
            yield item


def _resolve_exec_target(exec_name: str) -> dict:
    target = _require_exec_name(exec_name)
    platform_value = _target_platform()
    arch_value = _target_arch()
    matches = []

    for package in _iter_packages():
        if not package_platform_matches(package, platform_value):
            continue
        if not package_arch_matches(package, arch_value):
            continue
        exec_item = (package.get('execs') or {}).get(target)
        if not isinstance(exec_item, dict) or not exec_item.get('enabled', True):
            continue
        try:
            package_key = select_package_key(package, platform_alias=platform_value, arch=arch_value)
            rel_path = resolve_exec_rel_path(package, target, package_key)
        except Exception:
            continue
        matches.append({
            'exec_name': target,
            'package_id': package.get('id') or '',
            'package_key': package_key,
            'executable_rel_path': rel_path,
            'package_meta': package,
            'exec_item': exec_item,
            'exec_options': {
                'arg_mode': exec_item.get('arg_mode') or 'raw_append',
                'cwd': exec_item.get('cwd') or '',
                'timeout_sec': exec_item.get('timeout_sec'),
            },
        })

    if not matches:
        raise ScriptSdkExternalToolError(f'External tool exec not found for current client: {target}')
    if len(matches) > 1:
        lines = [f'Ambiguous external tool exec for current client: {target}', '', 'Matched:']
        for item in matches:
            lines.append(f'- {item.get("exec_name")} -> {item.get("package_id")}')
        lines.append('Keep exec names unique for the current platform/arch.')
        raise ScriptSdkExternalToolError('\n'.join(lines))
    return matches[0]


def _client_package_context(package: dict, package_key: str) -> dict:
    version = _safe_text(package.get('version')) or 'default'
    package_id = _safe_text(package.get('id'))
    package_file = (package.get('platform_packages') or {}).get(package_key) or {}
    context_payload = {
        'id': package_id,
        'package_id': package_id,
        'name': _safe_text(package.get('name')) or package_id,
        'display_name': _safe_text(package.get('display_name')) or package_id,
        'version': version,
        'platform': _target_platform(),
        'arch': _target_arch(),
        'package_key': package_key,
        'package_root': package_file.get('root') or '',
        'external_tools_root': EXTERNAL_TOOLS_INSTALL_ROOT,
        'external_tools_runtime': EXTERNAL_TOOLS_RUNTIME_ROOT,
        'runtime_dir': EXTERNAL_TOOLS_RUNTIME_ROOT,
    }
    install_template = _safe_text((package.get('install') or {}).get('install_dir'))
    if not install_template:
        install_template = '{{external_tools_root}}/{{package_id}}/{{version}}/{{package_key}}'
    context_payload['install_dir'] = render_value(install_template, context_payload)

    rel_execs = {}
    raw_bins = {}
    for name in (package.get('execs') or {}).keys():
        try:
            rel_path = resolve_exec_rel_path(package, name, package_key).lstrip('/\\')
        except Exception:
            continue
        rel_execs[name] = rel_path
        raw_bins[name] = os.path.join(context_payload['install_dir'], rel_path)
    context_payload['exec'] = rel_execs
    context_payload['bin'] = raw_bins
    return context_payload


def _package_file(package: dict, package_key: str) -> dict:
    value = (package.get('platform_packages') or {}).get(package_key)
    if not isinstance(value, dict):
        raise ScriptSdkExternalToolError(f'package build not found: {package_key}')
    return value


def _client_skip_path(package: dict, package_key: str, context_payload: dict) -> str:
    package_file = _package_file(package, package_key)
    install = package.get('install') if isinstance(package.get('install'), dict) else {}
    template = _safe_text(package_file.get('skip_if_exists') or install.get('skip_if_exists'))
    if not template:
        template = '{{install_dir}}'
    return render_value(template, context_payload)


def _client_download_url(package_file: dict) -> str:
    filename = _safe_text(package_file.get('filename'))
    download_url = _safe_text(package_file.get('download_url'))
    if download_url:
        return download_url
    if filename:
        return f'/api/external-tools/packages/{filename}'
    return ''


def _build_exec_payload(exec_name: str, raw_args: Any = '', cwd: str = '') -> dict:
    target = _resolve_exec_target(exec_name)
    package = target.get('package_meta') or {}
    package_key = target.get('package_key') or select_package_key(package, platform_alias=_target_platform(), arch=_target_arch())
    package_file = _package_file(package, package_key)
    context_payload = _client_package_context(package, package_key)
    exec_item = target.get('exec_item') if isinstance(target.get('exec_item'), dict) else {}
    exec_options = target.get('exec_options') if isinstance(target.get('exec_options'), dict) else {}
    rel_path = resolve_exec_rel_path(package, exec_name, package_key)
    payload = client_exec_payload(
        package,
        context_payload,
        source=_safe_text(package_file.get('source') or package.get('source')),
        filename=_safe_text(package_file.get('filename')),
        download_url=_client_download_url(package_file),
        executable_rel_path=rel_path,
        skip_if_exists=_client_skip_path(package, package_key, context_payload),
        exec_name=exec_name,
        exec_options={
            'arg_mode': exec_options.get('arg_mode') or exec_item.get('arg_mode') or 'raw_append',
            'cwd': cwd or exec_options.get('cwd') or exec_item.get('cwd') or '',
            'timeout_sec': exec_options.get('timeout_sec') if exec_options.get('timeout_sec') is not None else exec_item.get('timeout_sec'),
        },
        raw_args=_coerce_raw_args(raw_args),
    )
    return payload


def _coerce_raw_args(raw_args: Any) -> str:
    if raw_args is None:
        return ''
    if isinstance(raw_args, str):
        return raw_args.strip()
    if isinstance(raw_args, (list, tuple)):
        return ' '.join(shlex.quote(str(item)) for item in raw_args)
    return str(raw_args).strip()


def _argv_extra(raw_args: Any) -> list[str]:
    if raw_args is None or raw_args == '':
        return []
    if isinstance(raw_args, (list, tuple)):
        return [str(item) for item in raw_args]
    return shlex.split(str(raw_args or '').strip())


def _install_status(exec_name: str) -> dict:
    payload = _build_exec_payload(exec_name)
    try:
        return _external_tool_service().install_status_payload(payload)
    except Exception as exc:
        raise ScriptSdkExternalToolError(str(exc) or f'Failed to get external tool install status: {exec_name}') from exc


def _not_installed_error(exec_name: str, detail: str = '') -> ScriptSdkExternalToolError:
    suffix = f' Detail: {detail}' if _safe_text(detail) else ''
    return ScriptSdkExternalToolError(
        f'External tool is not installed for current client: {exec_name}. '
        f'Install it from External Tool Manager before running xt.tool({exec_name!r}).{suffix}'
    )


def _resolve_timeout(payload: dict, timeout):
    if timeout is not None:
        return timeout
    exec_options = payload.get('exec_options') if isinstance(payload.get('exec_options'), dict) else {}
    timeout_sec = exec_options.get('timeout_sec')
    try:
        timeout_sec = float(timeout_sec)
    except Exception:
        return None
    return timeout_sec if timeout_sec > 0 else None


def run(exec_name: str, raw_args: Any = '', *, timeout=None, cwd: str = '') -> ExternalToolExecResult:
    normalized_exec_name = _require_exec_name(exec_name)
    payload = _build_exec_payload(normalized_exec_name, raw_args=raw_args, cwd=cwd)
    service = _external_tool_service()
    status = service.install_status_payload(payload)

    if not status.get('installed'):
        raise _not_installed_error(normalized_exec_name, status.get('message') or status.get('error') or '')

    executable_path = _safe_text(status.get('executable_path'))
    if not executable_path or not os.path.exists(executable_path):
        raise _not_installed_error(normalized_exec_name, f'executable not found: {executable_path or "empty"}')

    service.chmod(executable_path)
    exec_options = payload.get('exec_options') if isinstance(payload.get('exec_options'), dict) else {}
    run_cwd = service.expand_path(cwd or exec_options.get('cwd') or os.getcwd())
    if not os.path.isdir(run_cwd):
        raise ScriptSdkExternalToolError(f'external tool cwd does not exist: {run_cwd}')

    owner = get_command_owner()
    if owner is not None and hasattr(owner, '_ensure_not_interrupted'):
        owner._ensure_not_interrupted()

    argv = [executable_path] + _argv_extra(raw_args)
    try:
        completed = subprocess.run(
            argv,
            shell=False,
            cwd=run_cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_resolve_timeout(payload, timeout),
            **(owner._build_process_creation_kwargs() if owner is not None and hasattr(owner, '_build_process_creation_kwargs') else {}),
        )
    except subprocess.TimeoutExpired as exc:
        raise ScriptSdkExternalToolError(f'External tool command timed out: {normalized_exec_name}') from exc
    except Exception as exc:
        raise ScriptSdkExternalToolError(str(exc) or f'Failed to execute external tool: {normalized_exec_name}') from exc

    if owner is not None and hasattr(owner, '_ensure_not_interrupted'):
        owner._ensure_not_interrupted()

    return ExternalToolExecResult(
        exec_name=normalized_exec_name,
        command=argv,
        returncode=int(completed.returncode or 0),
        stdout=completed.stdout or '',
        stderr=completed.stderr or '',
        executable=executable_path,
    )


def tool(exec_name: str) -> ExternalToolHandle:
    return ExternalToolHandle(exec_name)


def is_installed(exec_name: str) -> bool:
    return tool(exec_name).is_installed


def which(exec_name: str) -> str:
    return tool(exec_name).which()


def __getattr__(name: str):
    if name.startswith('_'):
        raise AttributeError(name)
    return ExternalToolHandle(name)
