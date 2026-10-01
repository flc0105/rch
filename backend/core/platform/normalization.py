from typing import Any


_PLATFORM_ALIASES = {
    'windows': 'win',
    'win': 'win',
    'win32': 'win',
    'nt': 'win',
    'darwin': 'mac',
    'mac': 'mac',
    'macos': 'mac',
    'osx': 'mac',
    'linux': 'linux',
    'ubuntu': 'linux',
    'debian': 'linux',
    'centos': 'linux',
    'fedora': 'linux',
    'redhat': 'linux',
    'rhel': 'linux',
    'alpine': 'linux',
    'arch': 'linux',
    'ios': 'ios',
    'iphone': 'ios',
    'ipad': 'ios',
    'iphoneos': 'ios',
    'ipados': 'ios',
}
_WILDCARD_PLATFORM_ALIASES = {'common', 'all', 'any', '*'}
_ARCH_ALIASES = {
    'x86_64': 'amd64',
    'x64': 'amd64',
    'amd64': 'amd64',
    'i386': '386',
    'i686': '386',
    'x86': '386',
    '386': '386',
    'aarch64': 'arm64',
    'arm64': 'arm64',
}


def normalize_platform_alias(value: Any, *, wildcard: bool = False, infer: bool = False) -> str:
    text = str(value or '').strip().lower()
    if not text:
        return ''
    if wildcard and text in _WILDCARD_PLATFORM_ALIASES:
        return '*'
    normalized = _PLATFORM_ALIASES.get(text)
    if normalized:
        return normalized
    if infer:
        if 'win' in text:
            return 'win'
        if 'darwin' in text or 'mac' in text:
            return 'mac'
        if 'linux' in text or any(name in text for name in ('ubuntu', 'debian', 'centos', 'fedora', 'redhat', 'rhel', 'alpine', 'arch')):
            return 'linux'
        if 'ios' in text or 'iphone' in text or 'ipad' in text:
            return 'ios'
    return text


def normalize_platform(value: Any) -> str:
    """Normalize platform selectors, including common/all/any to wildcard '*'."""
    return normalize_platform_alias(value, wildcard=True)


def normalize_arch(value: Any) -> str:
    text = str(value or '').strip().lower().replace('-', '_')
    return _ARCH_ALIASES.get(text, text)


def platform_key(platform_alias: Any, arch: Any) -> str:
    platform_value = normalize_platform_alias(platform_alias, wildcard=True)
    arch_value = normalize_arch(arch)
    if not platform_value or not arch_value:
        return ''
    return f'{platform_value}-{arch_value}'


def normalize_platforms(values, *, wildcard: bool = True) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        candidates = [values]
    elif isinstance(values, (list, tuple, set)):
        candidates = list(values)
    else:
        return []

    result = []
    seen = set()
    for item in candidates:
        normalized = normalize_platform_alias(item, wildcard=wildcard)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def is_platform_supported(target_platform, allowed_platforms) -> bool:
    normalized_allowed = normalize_platforms(allowed_platforms, wildcard=True)
    if not normalized_allowed or '*' in normalized_allowed:
        return True
    normalized_target = normalize_platform_alias(target_platform, wildcard=True)
    return bool(normalized_target and normalized_target in normalized_allowed)
