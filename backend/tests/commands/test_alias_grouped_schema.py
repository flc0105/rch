"""Alias definitions accept only the canonical platform-grouped shape."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _alias_manager_class():
    path = Path(__file__).resolve().parents[2] / 'server/application/command/alias_manager.py'
    spec = importlib.util.spec_from_file_location('_alias_grouped_schema_test', path)
    module = importlib.util.module_from_spec(spec)
    fake_config = ModuleType('server.config.config')
    fake_config.ALIAS_PATH = '/unused/aliases.json'
    saved = sys.modules.get('server.config.config')
    try:
        sys.modules['server.config.config'] = fake_config
        spec.loader.exec_module(module)
    finally:
        if saved is None:
            sys.modules.pop('server.config.config', None)
        else:
            sys.modules['server.config.config'] = saved
    return module.AliasManager


def test_platform_grouped_aliases_load_and_flat_aliases_are_rejected():
    cls = _alias_manager_class()
    manager = cls.__new__(cls)
    assert manager._normalize_alias_payload({'common': {'ls': 'shell ls'}, 'mac': {'ls': 'shell pwd'}})['mac'] == {'ls': 'shell pwd'}
    with pytest.raises(ValueError, match='Unknown alias platform groups'):
        manager._normalize_alias_payload({'ls': 'shell ls'})
    with pytest.raises(ValueError, match='must be an object'):
        manager._normalize_alias_payload({'common': 'not a mapping'})
