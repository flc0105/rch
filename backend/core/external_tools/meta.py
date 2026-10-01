import os
from copy import deepcopy
from typing import Any

from core.platform.normalization import normalize_arch, normalize_platform, platform_key


def normalize_param(item: Any) -> dict:
    if not isinstance(item, dict):
        return {}
    name = str(item.get('name') or '').strip()
    if not name:
        return {}
    param = dict(item)
    param['name'] = name
    param['type'] = str(item.get('type') or 'string').strip().lower() or 'string'
    param['required'] = bool(item.get('required'))
    param['description'] = str(item.get('description') or '').strip()
    return param


def normalize_params(values: Any) -> list[dict]:
    source = values if isinstance(values, list) else []
    return [param for param in (normalize_param(item) for item in source) if param]


def normalize_compatible_targets(values: Any, package_key: str) -> list[dict]:
    if values in (None, ''):
        return []
    if not isinstance(values, list):
        raise ValueError(f'platform package {package_key} compatible_targets must be a list')

    result = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(f'platform package {package_key} compatible_targets[{index}] must be an object')
        platform_value = normalize_platform(item.get('platform'))
        arch_value = normalize_arch(item.get('arch'))
        if not platform_value or not arch_value:
            raise ValueError(f'platform package {package_key} compatible_targets[{index}] requires platform and arch')

        normalized = dict(item)
        normalized['platform'] = platform_value
        normalized['arch'] = arch_value
        requires = normalized.get('requires')
        normalized['requires'] = [str(value).strip() for value in requires if str(value).strip()] if isinstance(requires, list) else []
        result.append(normalized)
    return result


def normalize_platform_package(key: str, item: Any) -> dict:
    package = dict(item) if isinstance(item, dict) else {}
    raw_key = str(package.get('key') or key or '').strip().lower().replace('_', '-')
    if not raw_key:
        platform_value = normalize_platform(package.get('platform'))
        arch_value = normalize_arch(package.get('arch'))
        raw_key = platform_key(platform_value, arch_value)
    if not raw_key:
        raise ValueError('platform package key is required')

    if '-' in raw_key:
        maybe_platform, maybe_arch = raw_key.split('-', 1)
    else:
        maybe_platform, maybe_arch = '', ''

    platform_value = normalize_platform(package.get('platform') or maybe_platform)
    arch_value = normalize_arch(package.get('arch') or maybe_arch)
    if not platform_value or not arch_value:
        raise ValueError(f'platform package {raw_key} requires platform and arch')

    filename = str(package.get('filename') or '').strip()
    if filename:
        package['filename'] = os.path.basename(filename)

    package['key'] = raw_key
    package['platform'] = platform_value
    package['arch'] = arch_value
    package['download_url'] = str(package.get('download_url') or '').strip()
    package['root'] = str(package.get('root') or '').strip()
    package['compatible_targets'] = normalize_compatible_targets(package.get('compatible_targets'), raw_key)
    return package


def normalize_platform_packages(meta: dict) -> dict[str, dict]:
    raw = meta.get('platform_packages')
    if not isinstance(raw, dict) or not raw:
        raise ValueError('platform_packages is required')

    packages = {}
    for key, value in raw.items():
        package = normalize_platform_package(str(key), value)
        packages[package['key']] = package
    return packages


def normalize_execs(meta: dict, platform_packages: dict[str, dict]) -> dict[str, dict]:
    raw = meta.get('execs')
    if not isinstance(raw, dict) or not raw:
        raise ValueError('execs is required')

    execs = {}
    for name, value in raw.items():
        exec_name = str(name or '').strip()
        if not exec_name:
            continue
        source = value if isinstance(value, dict) else {}
        paths = source.get('paths') if isinstance(source.get('paths'), dict) else {}
        normalized_paths = {}
        for key, path in paths.items():
            package_key = str(key or '').strip().lower().replace('_', '-')
            if package_key in platform_packages and str(path or '').strip():
                normalized_paths[package_key] = str(path or '').strip()
        if not normalized_paths:
            raise ValueError(f'exec {exec_name} requires paths for platform packages')
        item = dict(source)
        item['name'] = exec_name
        item['paths'] = normalized_paths
        item['description'] = str(item.get('description') or '').strip()
        item['enabled'] = bool(item.get('enabled', True))
        item['arg_mode'] = str(item.get('arg_mode') or 'raw_append').strip() or 'raw_append'
        execs[exec_name] = item
    if not execs:
        raise ValueError('execs is required')
    return execs


def normalize_module(package: dict, item: Any) -> dict:
    if not isinstance(item, dict):
        return {}
    module_id = str(item.get('id') or item.get('name') or '').strip()
    if not module_id:
        return {}
    module = deepcopy(item)
    package_id = package.get('id') or ''
    tool_id = f'{package_id}.{module_id}'
    module['id'] = module_id
    module['tool_id'] = tool_id
    module['package_id'] = package_id
    module['name'] = str(module.get('name') or module_id).strip() or module_id
    module['display_name'] = str(module.get('display_name') or module.get('name') or module_id).strip() or module_id
    module['description'] = str(module.get('description') or package.get('description') or '').strip()
    module['version'] = str(module.get('version') or package.get('version') or '').strip()
    module['category'] = str(module.get('category') or package.get('category') or '').strip()
    module['tags'] = module.get('tags') if isinstance(module.get('tags'), list) else list(package.get('tags') or [])
    module['execution'] = str(module.get('execution') or '').strip().lower()
    if module['execution'] not in ('daemon', 'oneshot'):
        raise ValueError(f'module {module_id} execution must be daemon or oneshot')
    module['exec'] = str(module.get('exec') or module_id).strip()
    if module['exec'] not in (package.get('execs') or {}):
        raise ValueError(f'module {module_id} references unknown exec: {module["exec"]}')

    common_params = normalize_params(package.get('params'))
    module_params = normalize_params(module.get('params'))
    module['params'] = common_params + module_params
    module['config'] = module.get('config') if isinstance(module.get('config'), dict) else {}
    module['runtime'] = module.get('runtime') if isinstance(module.get('runtime'), dict) else {}
    if isinstance(module.get('runtimes'), list):
        module['runtimes'] = module.get('runtimes')
    elif isinstance(module.get('runtime_variants'), list):
        module['runtimes'] = module.get('runtime_variants')
    else:
        module['runtimes'] = []
    module['lifecycle'] = module.get('lifecycle') if isinstance(module.get('lifecycle'), dict) else (package.get('lifecycle') if isinstance(package.get('lifecycle'), dict) else {})
    module['package_display_name'] = package.get('display_name') or package_id
    return module


def derive_package_platforms(platform_packages: dict[str, dict]) -> list[str]:
    result = []
    seen = set()
    for item in platform_packages.values():
        value = normalize_platform(item.get('platform'))
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def derive_package_arches(platform_packages: dict[str, dict]) -> list[str]:
    result = []
    seen = set()
    for item in platform_packages.values():
        value = normalize_arch(item.get('arch'))
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_meta(meta: dict, path: str = '') -> dict:
    item = deepcopy(meta)
    package_id = str(item.get('id') or item.get('name') or '').strip()
    if not package_id:
        raise ValueError('external tool package id is required')

    item['id'] = package_id
    item['name'] = str(item.get('name') or package_id).strip() or package_id
    item['display_name'] = str(item.get('display_name') or item.get('name') or package_id).strip() or package_id
    item['description'] = str(item.get('description') or '').strip()
    item['version'] = str(item.get('version') or '').strip()
    item['category'] = str(item.get('category') or '').strip()
    item['tags'] = item.get('tags') if isinstance(item.get('tags'), list) else []
    item['params'] = normalize_params(item.get('params'))

    platform_packages = normalize_platform_packages(item)
    item['platform_packages'] = platform_packages
    item['package_keys'] = sorted(platform_packages.keys())
    item['platforms'] = derive_package_platforms(platform_packages)
    item['arches'] = derive_package_arches(platform_packages)
    item['arch'] = ','.join(item['arches']) if len(item['arches']) > 1 else (item['arches'][0] if item['arches'] else '')
    item['execs'] = normalize_execs(item, platform_packages)

    item['install'] = item.get('install') if isinstance(item.get('install'), dict) else {}
    item['config'] = item.get('config') if isinstance(item.get('config'), dict) else {}
    item['runtime'] = item.get('runtime') if isinstance(item.get('runtime'), dict) else {}
    item['lifecycle'] = item.get('lifecycle') if isinstance(item.get('lifecycle'), dict) else {}

    modules = []
    for module_item in (item.get('modules') if isinstance(item.get('modules'), list) else []):
        module = normalize_module(item, module_item)
        if module:
            modules.append(module)
    if not modules:
        raise ValueError('modules is required')
    item['modules'] = modules

    if path:
        item['_meta_path'] = os.path.abspath(path)
    return item
