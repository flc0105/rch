"""Shared external tool payload builders used by server and client."""
from __future__ import annotations

import shlex
from typing import Any

from core.external_tools.install_status import INSTALL_STATUS_INSTALLED, INSTALL_STATUS_NOT_INSTALLED


def primary_exec_name(package: dict, module: dict | None = None) -> str:
    source_package = package if isinstance(package, dict) else {}
    source_module = module if isinstance(module, dict) else {}
    if source_module.get('exec'):
        return str(source_module.get('exec') or '').strip()
    for name in (source_package.get('execs') or {}).keys():
        return str(name or '').strip()
    return ''


def package_identity_payload(
    package: dict,
    context: dict,
    *,
    action: str,
    source: str = '',
    side: str = 'client',
    tool_id: str = '',
) -> dict:
    source_package = package if isinstance(package, dict) else {}
    source_context = context if isinstance(context, dict) else {}
    package_id = str(source_package.get('id') or source_context.get('package_id') or '').strip()
    return {
        'action': action,
        'tool_id': tool_id or package_id,
        'package_id': package_id,
        'display_name': source_package.get('display_name') or package_id,
        'version': source_package.get('version') or '',
        'source': source,
        'side': side,
        'platform': source_context.get('platform') or '',
        'arch': source_context.get('arch') or '',
        'package_key': source_context.get('package_key') or '',
    }


def module_identity_payload(
    module: dict,
    context: dict,
    *,
    action: str,
    source: str = '',
    side: str = 'client',
) -> dict:
    source_module = module if isinstance(module, dict) else {}
    source_context = context if isinstance(context, dict) else {}
    return {
        'action': action,
        'tool_id': source_module.get('tool_id') or source_context.get('tool_id') or '',
        'package_id': source_module.get('package_id') or source_context.get('package_id') or '',
        'module_id': source_module.get('id') or source_module.get('module_id') or source_context.get('module_id') or '',
        'display_name': source_module.get('display_name') or source_module.get('tool_id') or source_context.get('tool_id') or '',
        'version': source_module.get('version') or source_context.get('version') or '',
        'source': source,
        'side': side,
        'platform': source_context.get('platform') or '',
        'arch': source_context.get('arch') or '',
        'package_key': source_context.get('package_key') or '',
    }


def package_archive_payload(
    *,
    filename: str,
    download_url: str,
    executable_rel_path: str = '',
    exec_paths: dict | None = None,
) -> dict:
    return {
        'filename': str(filename or '').strip(),
        'download_url': str(download_url or '').strip(),
        'executable_rel_path': str(executable_rel_path or '').strip(),
        'exec_paths': dict(exec_paths or {}),
    }


def install_section_payload(*, install_dir: str, skip_if_exists: str = '') -> dict:
    return {
        'install_dir': install_dir or '',
        'skip_if_exists': skip_if_exists or install_dir or '',
    }


def config_payload_from_rendered(rendered_meta: dict, content_renderer) -> dict:
    source = rendered_meta if isinstance(rendered_meta, dict) else {}
    config = source.get('config') if isinstance(source.get('config'), dict) else {}
    if not config.get('target') or config.get('template') is None:
        return {}
    return {
        'target': config.get('target'),
        'content': content_renderer(str(config.get('template'))),
    }


def client_install_payload(
    package: dict,
    context: dict,
    *,
    source: str,
    filename: str,
    download_url: str,
    executable_rel_path: str,
    skip_if_exists: str,
    action: str = 'install',
) -> dict:
    payload = package_identity_payload(package, context, action=action, source=source, side='client')
    payload.update({
        'package': package_archive_payload(
            filename=filename,
            download_url=download_url,
            executable_rel_path=executable_rel_path,
            exec_paths=(context or {}).get('exec') or {},
        ),
        'install': install_section_payload(
            install_dir=(context or {}).get('install_dir') or '',
            skip_if_exists=skip_if_exists,
        ),
    })
    return payload


def client_module_payload(
    module: dict,
    context: dict,
    *,
    action: str,
    source: str,
    filename: str,
    download_url: str,
    executable_rel_path: str,
    skip_if_exists: str,
    params: dict | None = None,
    runtime: dict | None = None,
    config: dict | None = None,
    lifecycle: dict | None = None,
    install_if_needed: bool = False,
    execution: str = '',
    run_id: str = '',
    timeout_sec: Any = None,
) -> dict:
    payload = module_identity_payload(module, context, action=action, source=source, side='client')
    source_context = context if isinstance(context, dict) else {}
    payload.update({
        'install_if_needed': bool(install_if_needed),
        'params': dict(params or {}),
        'package': package_archive_payload(
            filename=filename,
            download_url=download_url,
            executable_rel_path=executable_rel_path,
            exec_paths=source_context.get('exec') or {},
        ),
        'install': install_section_payload(
            install_dir=source_context.get('install_dir') or '',
            skip_if_exists=skip_if_exists,
        ),
        'config': dict(config or {}),
        'runtime': dict(runtime or {}),
    })
    if lifecycle is not None:
        payload['lifecycle'] = dict(lifecycle or {})
    instance_id = source_context.get('instance_id') or ''
    if action == 'start' or instance_id:
        payload['instance_id'] = instance_id or 'default'
        payload['instance_name'] = source_context.get('instance_name') or payload['instance_id']
    if execution:
        payload['execution'] = execution
    if run_id:
        payload['run_id'] = run_id
    if timeout_sec is not None:
        payload['timeout_sec'] = timeout_sec
    return payload


def client_action_payload(
    module: dict,
    *,
    action: str,
    instance_id: str,
    params: dict | None,
    runtime: dict,
    max_bytes: int,
    cursor: str | None = None,
) -> dict:
    source_module = module if isinstance(module, dict) else {}
    package_id = str(source_module.get('package_id') or '').strip()
    module_id = str(source_module.get('id') or source_module.get('module_id') or '').strip()
    result = {
        'action': action,
        'tool_id': source_module.get('tool_id') or '',
        'package_id': package_id,
        'module_id': module_id,
        'display_name': source_module.get('display_name') or source_module.get('tool_id') or '',
        'version': source_module.get('version') or '',
        'side': 'client',
        'instance_id': instance_id,
        'instance_name': instance_id,
        'params': dict(params or {}),
        'runtime': dict(runtime or {}),
        'lifecycle': dict(source_module.get('lifecycle') or {}),
        'max_bytes': int(max_bytes),
    }
    if cursor is not None:
        result['cursor'] = str(cursor)
    return result


def client_exec_payload(
    package: dict,
    context: dict,
    *,
    source: str,
    filename: str,
    download_url: str,
    executable_rel_path: str,
    skip_if_exists: str,
    exec_name: str,
    exec_options: dict | None = None,
    raw_args: str = '',
) -> dict:
    payload = client_install_payload(
        package,
        context,
        source=source,
        filename=filename,
        download_url=download_url,
        executable_rel_path=executable_rel_path,
        skip_if_exists=skip_if_exists,
        action='exec',
    )
    payload['install_if_needed'] = False
    payload['exec_name'] = str(exec_name or '').strip()
    payload['exec_options'] = dict(exec_options or {})
    payload['raw_args'] = raw_args or ''
    return payload


def client_install_status_result(
    payload: dict,
    *,
    install_dir: str,
    install_dir_exists: bool,
    skip_if_exists: str,
    executable_path: str,
    exec_paths: dict,
    missing_execs: dict,
    cache: dict,
    commands: dict,
    install_log: str,
    install_log_path: str,
) -> dict:
    source = payload if isinstance(payload, dict) else {}
    installed = bool(install_dir_exists and not missing_execs)
    install_status = INSTALL_STATUS_INSTALLED if installed else INSTALL_STATUS_NOT_INSTALLED
    display_name = source.get('display_name') or source.get('tool_id') or 'external tool'
    return {
        'tool_id': source.get('tool_id') or '',
        'package_id': source.get('package_id') or source.get('tool_id') or '',
        'module_id': source.get('module_id') or '',
        'display_name': display_name,
        'source': source.get('source') or '',
        'side': source.get('side') or 'client',
        'platform': source.get('platform') or '',
        'arch': source.get('arch') or '',
        'package_key': source.get('package_key') or '',
        'installed': installed,
        'install_status': install_status,
        'install_dir': install_dir,
        'install_dir_exists': bool(install_dir_exists),
        'skip_path': skip_if_exists,
        'executable_path': executable_path,
        'exec_paths': dict(exec_paths or {}),
        'missing_execs': dict(missing_execs or {}),
        'cache': dict(cache or {}),
        'cached': bool((cache or {}).get('cached')),
        'cache_path': (cache or {}).get('cache_path') or '',
        'command': shlex.quote(executable_path) if executable_path else '',
        'commands': dict(commands or {}),
        'install_log': install_log or '',
        'install_log_path': install_log_path or '',
        'message': (
            f'{display_name} is installed at {install_dir}'
            if installed
            else f'{display_name} is not installed. Please install it first.'
        ),
    }


def client_install_status_error_payload(tool_payload: dict, error: Exception | str) -> dict:
    source = tool_payload if isinstance(tool_payload, dict) else {}
    message = str(error or '')
    return {
        'tool_id': source.get('tool_id') or '',
        'package_id': source.get('package_id') or source.get('tool_id') or '',
        'display_name': source.get('display_name') or source.get('tool_id') or '',
        'side': source.get('side') or 'client',
        'installed': None,
        'install_status': 'error',
        'install_dir': '',
        'skip_path': '',
        'executable_path': '',
        'command': '',
        'error': message,
        'message': message,
    }
