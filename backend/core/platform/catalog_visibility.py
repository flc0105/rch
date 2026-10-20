"""Visibility for terminal catalogs/completion; never restrict explicit execution.

Declared metadata.platforms is authoritative.  Older scripts/jobs without that
field retain the conventional common/<platform> directory visibility.
"""
from core.platform.normalization import is_platform_supported, normalize_platform_alias

KNOWN_PLATFORMS = frozenset({'mac', 'win', 'linux', 'ios'})


def visible_on_platform(item, platform: str) -> bool:
    metadata = item.get('metadata') or {}
    allowed = metadata.get('platforms') or []
    current = normalize_platform_alias(platform, infer=True)
    if allowed:
        return is_platform_supported(current, allowed)
    path = str(item.get('path') or item.get('job_name') or item.get('name') or '').replace('\\', '/')
    root = path.split('/', 1)[0].lower()
    normalized_root = normalize_platform_alias(root, infer=False, wildcard=True)
    if normalized_root in KNOWN_PLATFORMS:
        return bool(current and normalized_root == current)
    if normalized_root == '*' or root in {'common', 'shared'}:
        return True
    # Unscoped modules with no schema are platform-agnostic.
    return normalized_root not in KNOWN_PLATFORMS
