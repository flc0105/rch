import os
from typing import Any, Callable

from core.platform.normalization import normalize_arch, normalize_platform
from core.external_tools.paths import expand_path


def select_module_runtime_for_platform(module: dict, platform_alias: Any, arch: Any) -> dict:
    source = module if isinstance(module, dict) else {}
    base = source.get('runtime') if isinstance(source.get('runtime'), dict) else {}
    selected = dict(base)
    variants = source.get('runtimes') if isinstance(source.get('runtimes'), list) else []
    target_platform = normalize_platform(platform_alias)
    target_arch = normalize_arch(arch)
    for item in variants:
        if not isinstance(item, dict):
            continue
        platform_value = normalize_platform(item.get('platform') or '*')
        arch_value = normalize_arch(item.get('arch') or '*') if item.get('arch') else '*'
        platform_ok = platform_value in ('*', target_platform)
        arch_ok = arch_value in ('*', 'all', target_arch)
        if platform_ok and arch_ok:
            overlay = dict(item)
            overlay.pop('platform', None)
            overlay.pop('arch', None)
            selected.update(overlay)
            break
    return selected


def resolved_exec_context(
    package: dict,
    package_key: str,
    install_dir: str,
    resolve_exec_rel_path: Callable[[dict, str, str], str],
    path_expander: Callable[[Any], str] = expand_path,
) -> tuple[dict, dict]:
    rel_execs = {}
    abs_bins = {}
    for exec_name in (package.get('execs') if isinstance(package, dict) else {}) or {}:
        try:
            rel_path = resolve_exec_rel_path(package, exec_name, package_key)
        except Exception:
            continue
        rel_path = str(rel_path or '').strip().lstrip('/\\')
        rel_execs[exec_name] = rel_path
        abs_bins[exec_name] = path_expander(os.path.join(install_dir, rel_path))
    return rel_execs, abs_bins


def missing_exec_paths(abs_bins: dict, path_expander: Callable[[Any], str] = expand_path) -> dict:
    missing = {}
    for name, path in (abs_bins or {}).items():
        expanded = path_expander(path)
        if not expanded or not os.path.isfile(expanded):
            missing[str(name)] = expanded
    return missing
