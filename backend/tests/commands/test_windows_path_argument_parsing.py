"""Windows drive paths are literal arguments, not POSIX escape sequences."""

from types import ModuleType, SimpleNamespace
from pathlib import Path
import importlib.util
import sys

import pytest

from core.utils.parsing import parse, split_shell_arguments


PATH = r'C:\Users\方良辰\AppData\Local\Temp\rch_client_temp\watchdog_logs\process_recovery_watchdog.log'


def _manager():
    # Load just the real AliasManager source without importing Server auth/Web dependencies.
    path = Path(__file__).resolve().parents[2] / 'server/application/command/alias_manager.py'
    spec = importlib.util.spec_from_file_location('_windows_path_alias_test', path)
    module = importlib.util.module_from_spec(spec)
    fake_config = ModuleType('server.config.config')
    fake_config.ALIAS_PATH = '/unused/test-aliases.json'
    original_config = sys.modules.get('server.config.config')
    try:
        sys.modules['server.config.config'] = fake_config
        spec.loader.exec_module(module)
    finally:
        if original_config is None:
            sys.modules.pop('server.config.config', None)
        else:
            sys.modules['server.config.config'] = original_config
    AliasManager = module.AliasManager
    instance = AliasManager.__new__(AliasManager)
    instance.aliases = instance._create_empty_aliases()
    instance.aliases['win']['cat'] = 'powershell Get-Content <path>'
    instance.aliases['common']['open'] = 'shell <path>'
    instance._ensure_fresh = lambda: None
    return instance


def _conn(platform):
    return SimpleNamespace(session_info=SimpleNamespace(os_alias=platform, os_type=platform))


def test_win_alias_preserves_backslashes_for_unicode_drive_path():
    expanded = _manager().resolve_alias('cat', PATH, conn=_conn('win'))['command']
    assert expanded == 'powershell Get-Content ' + PATH
    assert parse(expanded)[1] == 'Get-Content ' + PATH


def test_win_alias_handles_quoted_drive_paths_and_named_arguments():
    manager = _manager()
    path_with_space = r'C:\Users\方良辰\My Logs\agent.log'
    assert manager._parse_provided_args(f'"{path_with_space}"', platform='win') == [path_with_space]
    assert manager._parse_provided_args(f'--path "{path_with_space}"', required_args=['path'], platform='win') == [path_with_space]
    assert manager._parse_provided_args('--path=' + PATH, required_args=['path'], platform='win') == [PATH]


def test_non_windows_alias_keeps_original_posix_escape_semantics():
    manager = _manager()
    assert manager._parse_provided_args(r'foo\ bar', platform='mac') == ['foo bar']
    assert split_shell_arguments(PATH, literal_backslashes=True) == [PATH]
    assert split_shell_arguments('foo\\ bar') == ['foo bar']


def test_unmatched_quotes_still_raise_on_windows():
    with pytest.raises(ValueError):
        split_shell_arguments('"C:\\Users\\bad', literal_backslashes=True)


def test_windows_external_tool_path_splitters_preserve_drive_separators(monkeypatch):
    from client.external_tools import launcher
    from core.external_tools import paths

    monkeypatch.setattr(launcher, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(paths, 'os', SimpleNamespace(name='nt'))
    assert launcher._normalize_prefix_args(f'--file "{PATH}"') == ['--file', PATH]
    assert paths.render_path_list(f'"{PATH}"') == [PATH]
