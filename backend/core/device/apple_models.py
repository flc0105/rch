"""Resolve Apple machine identifiers, mobile SoCs and macOS release names."""

import json
from functools import lru_cache
from pathlib import Path


_MODEL_DATA_PATH = Path(__file__).with_name('apple_model_names.json')


@lru_cache(maxsize=1)
def _load_model_data():
    try:
        payload = json.loads(_MODEL_DATA_PATH.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _lookup(section, key):
    mapping = _load_model_data().get(section)
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_apple_model_name(identifier):
    """Use a friendly hardware name when available; retain unknown identifiers."""
    identifier = str(identifier or '').strip()
    return (_lookup('models', identifier) or identifier) if identifier else None


def resolve_apple_chip_name(identifier):
    """Look up a mobile device's SoC; unknown devices have no asserted chip name."""
    return _lookup('chip_models', str(identifier or '').strip())


def resolve_macos_product(version):
    """Build a user-facing macOS release name from the maintained version table."""
    version = str(version or '').strip()
    if not version:
        return 'macOS'
    segments = version.split('.')
    major = '.'.join(segments[:2]) if segments[0] == '10' and len(segments) > 1 else segments[0]
    name = _lookup('macos_names', major)
    return f'macOS {name} {version}' if name else f'macOS {version}'
