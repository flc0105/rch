import logging
from typing import Any

from core.platform.normalization import normalize_arch, normalize_platform, platform_key


logger = logging.getLogger(__name__)


def package_platform_matches(package: dict, platform_alias: Any = '') -> bool:
    target = normalize_platform(platform_alias or '')
    if not target:
        return False

    for item in (package.get('platform_packages') or {}).values():
        item_platform = normalize_platform(item.get('platform'))
        if item_platform in ('*', target):
            return True

        for compatible in item.get('compatible_targets') or []:
            compatible_platform = normalize_platform(compatible.get('platform'))
            if compatible_platform in ('*', target):
                return True

    return False


def package_arch_matches(package: dict, arch: Any = '') -> bool:
    target = normalize_arch(arch or '')
    if not target:
        return False

    for item in (package.get('platform_packages') or {}).values():
        item_arch = normalize_arch(item.get('arch'))
        if item_arch in ('*', 'all') or item_arch == target:
            return True

        for compatible in item.get('compatible_targets') or []:
            compatible_arch = normalize_arch(compatible.get('arch'))
            if compatible_arch in ('*', 'all') or compatible_arch == target:
                return True

    return False


def select_package_key(package: dict, platform_alias: Any = '', arch: Any = '', log: logging.Logger | None = None) -> str:
    log = log or logger
    packages = package.get('platform_packages') if isinstance(package.get('platform_packages'), dict) else {}
    package_id = package.get('id') or 'package'
    if not packages:
        log.warning('[external-tools] package has no platform packages: package_id=%s', package_id)
        raise ValueError(f'{package_id} has no platform packages')

    target_platform = normalize_platform(platform_alias or '')
    target_arch = normalize_arch(arch or '')
    if not target_platform or not target_arch:
        log.warning(
            '[external-tools] missing target platform/arch: package_id=%s target=%s/%s supported=%s raw_platform=%s raw_arch=%s',
            package_id,
            target_platform or 'unknown',
            target_arch or 'unknown',
            sorted(packages.keys()),
            platform_alias or '',
            arch or '',
        )
        raise ValueError(f'target platform and arch are required for {package_id}, got {target_platform or "unknown"}/{target_arch or "unknown"}')

    exact_key = platform_key(target_platform, target_arch)
    if exact_key and exact_key in packages:
        log.info(
            '[external-tools] selected exact package build: package_id=%s target=%s/%s package_key=%s supported=%s',
            package_id,
            target_platform,
            target_arch,
            exact_key,
            sorted(packages.keys()),
        )
        return exact_key

    matches = []
    for key, item in packages.items():
        platform_ok = item.get('platform') == '*' or item.get('platform') == target_platform
        arch_ok = item.get('arch') in ('*', 'all') or item.get('arch') == target_arch
        if platform_ok and arch_ok:
            matches.append((key, 'direct'))
            continue

        for compatible in item.get('compatible_targets') or []:
            compatible_platform = normalize_platform(compatible.get('platform'))
            compatible_arch = normalize_arch(compatible.get('arch'))
            if compatible_platform == target_platform and compatible_arch == target_arch:
                matches.append((key, 'explicit-compatible'))
                break

    if len(matches) == 1:
        match_key, match_reason = matches[0]
        log.info(
            '[external-tools] selected package build: package_id=%s target=%s/%s package_key=%s reason=%s supported=%s',
            package_id,
            target_platform,
            target_arch,
            match_key,
            match_reason,
            sorted(packages.keys()),
        )
        return match_key
    if matches:
        match_keys = [key for key, _reason in matches]
        log.warning(
            '[external-tools] ambiguous package build: package_id=%s target=%s/%s matches=%s supported=%s',
            package_id,
            target_platform,
            target_arch,
            matches,
            sorted(packages.keys()),
        )
        raise ValueError(f'Ambiguous platform package for {package_id}: {target_platform}/{target_arch} -> {", ".join(match_keys)}')

    log.warning(
        '[external-tools] unsupported package target: package_id=%s target=%s/%s supported=%s raw_platform=%s raw_arch=%s',
        package_id,
        target_platform,
        target_arch,
        sorted(packages.keys()),
        platform_alias or '',
        arch or '',
    )
    raise ValueError(f'{package_id} does not support {target_platform}/{target_arch}')


def resolve_exec_rel_path(package: dict, exec_name: Any, package_key: Any) -> str:
    execs = package.get('execs') if isinstance(package.get('execs'), dict) else {}
    exec_item = execs.get(str(exec_name or '').strip())
    if not isinstance(exec_item, dict):
        raise ValueError(f'exec not found: {exec_name}')
    paths = exec_item.get('paths') if isinstance(exec_item.get('paths'), dict) else {}
    rel_path = str(paths.get(str(package_key or '').strip()) or '').strip()
    if not rel_path:
        raise ValueError(f'exec {exec_name} does not support {package_key}')
    return rel_path
