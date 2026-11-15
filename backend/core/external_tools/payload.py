"""Shared external tool payload builders used by server and client."""
from __future__ import annotations

import shlex
from typing import Any

from core.external_tools.install_status import INSTALL_STATUS_INSTALLED, INSTALL_STATUS_NOT_INSTALLED


def primary_binary_name(package: dict, module: dict | None = None) -> str:
    source_package = package if isinstance(package, dict) else {}
    source_module = module if isinstance(module, dict) else {}
    if source_module.get('binary'):
        return str(source_module.get('binary') or '').strip()
    for name in (source_package.get('binaries') or {}).keys():
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
            exec_paths=(context or {}).get('binary') or {},
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
            exec_paths=source_context.get('binary') or {},
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
    max_bytes: int,
    cursor: str | None = None,
) -> dict:
    """Only transmit fields consumed by this instance action.

    Client resolves its own managed runtime paths from the validated identity.
    """
    source_module = module if isinstance(module, dict) else {}
    result = {
        'tool_id': source_module.get('tool_id') or '',
        'package_id': source_module.get('package_id') or '',
        'module_id': source_module.get('id') or source_module.get('module_id') or '',
        'instance_id': instance_id,
    }
    if action == 'stop':
        result['lifecycle'] = dict(source_module.get('lifecycle') or {})
    if action == 'logs':
        result['max_bytes'] = int(max_bytes)
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


# The External Tool action decides its wire payload. Domain builders may carry
# richer Server-side metadata, but the Client receives only consumed fields.
def client_control_request(action, source: dict) -> dict:
    from core.protocol.control import ExternalToolAction as A

    action = A(action)
    value = source or {}

    def fields(item, names):
        return {key: item[key] for key in names if key in item and item[key] is not None}

    identity = ('tool_id', 'package_id', 'module_id', 'instance_id')
    target = ('package_id', 'platform', 'arch', 'package_key')
    package_install = ('filename', 'download_url', 'executable_rel_path', 'exec_paths')
    package_status = ('filename', 'executable_rel_path', 'exec_paths')
    install_fields = ('install_dir', 'skip_if_exists')

    def package_request(*, download=False):
        result = fields(value, target)
        package = fields(value.get('package') or {}, package_install if download else package_status)
        install = fields(value.get('install') or {}, install_fields)
        if package:
            result['package'] = package
        if install:
            result['install'] = install
        return result

    if action == A.GET_INSTALL_STATUSES:
        return {**({'include_details': True} if value.get('include_details') is True else {}), 'tools': [({**fields(tool, target),
                            'package': fields(tool.get('package') or {}, package_status),
                            'install': fields(tool.get('install') or {}, install_fields)})
                          if not tool.get('error') else fields(tool, ('package_id', 'error'))
                          for tool in value.get('tools') or []]}
    if action == A.LIST_INSTANCES:
        return {'tools': [fields(tool, (*identity, 'instance_ids')) for tool in value.get('tools') or []]}
    if action == A.RESOLVE_LAUNCHER:
        return fields(value, ('launcher',))
    if action == A.UNINSTALL_PACKAGE:
        return {**fields(value, target), **({'install': fields(value['install'], ('install_dir',))} if value.get('install') else {})}
    if action == A.CLEAR_PACKAGE_CACHE:
        return {**fields(value, target), 'package': fields(value.get('package') or {}, ('filename',))}
    if action == A.INSTALL_PACKAGE:
        return package_request(download=True)
    if action in (A.READ_INSTANCE, A.READ_INSTANCE_LOGS, A.STOP_INSTANCE,
                  A.REMOVE_INSTANCE, A.CLEAR_INSTANCE_LOGS):
        result = fields(value, identity)
        if action == A.READ_INSTANCE_LOGS:
            result.update(fields(value, ('max_bytes', 'cursor')))
        if action == A.STOP_INSTANCE:
            result.update(fields(value, ('lifecycle',)))
        return result
    if action == A.CREATE_INSTANCE:
        return {**fields(value, (*identity, 'platform', 'arch', 'package_key', 'params'))}
    if action == A.PREVIEW_INSTANCE:
        return {**fields(value, (*identity, 'platform', 'arch', 'package_key', 'launcher', 'launcher_override')),
                'runtime': fields(value.get('runtime') or {}, ('argv', 'cwd'))}
    if action in (A.START_INSTANCE, A.RESTART_INSTANCE, A.RUN_ONESHOT, A.EXEC):
        result = package_request()
        result.update(fields(value, (*identity, 'display_name', 'params', 'config',
                                    'launcher', 'launcher_override')))
        if action == A.EXEC:
            result.update(fields(value, ('exec_name', 'raw_args')))
            result['exec_options'] = fields(value.get('exec_options') or {}, ('cwd', 'timeout_sec', 'launcher'))
            for key in ('tool_id', 'module_id', 'instance_id', 'params', 'config',
                        'launcher', 'launcher_override', 'display_name'):
                result.pop(key, None)
        else:
            result['install_if_needed'] = False
            runtime = fields(value.get('runtime') or {},
                ('argv', 'cwd', 'stdout') if action == A.RUN_ONESHOT else
                ('argv', 'cwd', 'stdout', 'stderr', 'pid_file', 'state_file'))
            if runtime:
                result['runtime'] = runtime
            if action == A.RUN_ONESHOT:
                result.update(fields(value, ('run_id', 'timeout_sec')))
                result['execution'] = 'oneshot'
                for key in ('params', 'instance_id', 'module_id'):
                    result.pop(key, None)
            elif action == A.RESTART_INSTANCE:
                result.update(fields(value, ('lifecycle',)))
            # Only the daemon's persisted state consumes params and display_name.
        return result
    raise ValueError(f'Unsupported external tool Control action: {action}')
