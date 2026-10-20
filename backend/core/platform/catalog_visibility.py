"""Script/Job terminal catalog visibility, driven only by declared metadata.platforms.

This controls discoverability in CLI lists and completion, never explicit execution.
Resources without a platform declaration do not appear in command catalogs.
"""
from core.platform.normalization import is_platform_supported, normalize_platform_alias


def visible_on_platform(item, platform: str) -> bool:
    metadata = item.get('metadata') or {}
    allowed = metadata.get('platforms') or []
    if not allowed:
        return False
    current = normalize_platform_alias(platform, infer=True)
    return is_platform_supported(current, allowed)
