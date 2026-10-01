from typing import Any

from core.platform.normalization import normalize_arch, normalize_platform


def require_target(platform_alias: Any, arch: Any, context: str) -> tuple[str, str]:
    platform_value = normalize_platform(platform_alias or '')
    arch_value = normalize_arch(arch or '')
    if not platform_value or not arch_value:
        raise ValueError(f'target platform and arch are required for {context}, got {platform_value or "unknown"}/{arch_value or "unknown"}')
    return platform_value, arch_value


def validate_payload_target(payload: dict, local_platform: Any, local_arch: Any, action: str = '') -> tuple[str, str]:
    source = payload if isinstance(payload, dict) else {}
    requested_platform = normalize_platform(source.get('platform'))
    requested_arch = normalize_arch(source.get('arch'))
    package_key = str(source.get('package_key') or '').strip()
    package_id = str(source.get('package_id') or source.get('tool_id') or '').strip()

    if not package_id:
        raise ValueError('external tool payload.package_id is required')
    if not package_key:
        raise ValueError(f'external tool payload.package_key is required for {package_id}')
    if not requested_platform or not requested_arch:
        raise ValueError(f'external tool payload platform/arch is required for {package_id}, got {requested_platform or "unknown"}/{requested_arch or "unknown"}')

    local_platform_value = normalize_platform(local_platform)
    local_arch_value = normalize_arch(local_arch)
    platform_ok = requested_platform in ('*', local_platform_value)
    arch_ok = requested_arch in ('*', 'all', local_arch_value)
    if not platform_ok or not arch_ok:
        suffix = f' during {action}' if action else ''
        raise ValueError(
            f'external tool target mismatch{suffix}: payload requests '
            f'{requested_platform}/{requested_arch} ({package_key}) but this client is {local_platform_value}/{local_arch_value}'
        )
    return requested_platform, requested_arch


def runtime_parts_from_payload(payload: dict) -> tuple[str, str, str]:
    source = payload if isinstance(payload, dict) else {}
    tool_id = str(source.get('tool_id') or '').strip()
    package_id = str(source.get('package_id') or '').strip()
    module_id = str(source.get('module_id') or '').strip()
    if (not package_id or not module_id) and '.' in tool_id:
        package_id, module_id = tool_id.split('.', 1)
    if not package_id:
        package_id = tool_id
    return tool_id, package_id, module_id
