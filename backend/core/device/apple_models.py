"""Resolve Apple hardware identifiers to human-readable product names."""

import json
from functools import lru_cache
from pathlib import Path


_MODEL_NAMES_PATH = Path(__file__).with_name('apple_model_names.json')


@lru_cache(maxsize=1)
def _load_model_names():
    try:
        payload = json.loads(_MODEL_NAMES_PATH.read_text(encoding='utf-8'))
        models = payload.get('models', {})
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(models, dict):
        return {}
    return {
        str(identifier): str(name)
        for identifier, name in models.items()
        if isinstance(identifier, str) and isinstance(name, str) and name.strip()
    }


def resolve_apple_model_name(identifier):
    """Return the product name when mapped, otherwise retain the raw identifier."""
    value = str(identifier or '').strip()
    if not value:
        return None
    return _load_model_names().get(value, value)
