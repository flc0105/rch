"""Regression: Quick History listing/replay and Alias name limit."""
from types import SimpleNamespace

import pytest

from server.application.command.alias_manager import AliasManager
from server.application.command.builtin_command_support import HistoryBuiltinSupport
from server.application.command.executor import CommandExecutor
from server.application.history.quick_history import QuickHistoryRecordPolicy


def test_quick_history_replay_filters_only_meta_commands():
    assert QuickHistoryRecordPolicy.is_history_replay_command('history run 3')
    assert QuickHistoryRecordPolicy.is_history_replay_command(' HISTORY  RUN   12 ')
    assert QuickHistoryRecordPolicy.is_history_replay_command('!7')
    assert not QuickHistoryRecordPolicy.is_history_replay_command('shell echo history run 3')
    assert not QuickHistoryRecordPolicy.is_history_replay_command('history')


def test_history_listing_and_replay_reindex_meta_entries():
    rows = [
        {'index': 1, 'command': 'history run 9'},
        {'index': 2, 'command': '!7'},
        {'index': 3, 'command': 'shell echo hello'},
        {'index': 4, 'command': 'now'},
    ]
    quick = SimpleNamespace(get_history_for_connection=lambda conn: rows)
    seen = []

    def processor(command):
        seen.append(command)
        return lambda: iter([(1, f'executed: {command}')])

    support = HistoryBuiltinSupport(quick, object(), lambda: '', lambda: processor)
    listing = list(support.history(''))
    assert '1  shell echo hello' in listing[0][1]
    assert '2  now' in listing[0][1]
    assert 'history run 9' not in listing[0][1]
    assert list(support.history('run 1'))[-1] == (1, 'executed: shell echo hello')
    assert list(support.history('run 2'))[-1] == (1, 'executed: now')
    assert seen == ['shell echo hello', 'now']
    assert CommandExecutor._rewrite_history_shortcut(CommandExecutor.__new__(CommandExecutor), '!1') == 'history run 1'
    with pytest.raises(ValueError, match='History index not found'):
        list(support.history('run 3'))


def test_alias_name_length_is_enforced_at_shared_write_boundary(tmp_path):
    manager = AliasManager.__new__(AliasManager)
    manager.alias_path = str(tmp_path / 'aliases.json')
    manager.aliases = manager._create_empty_aliases()
    max_chars = manager.MAX_ALIAS_NAME_LENGTH
    assert max_chars == 32
    manager.add_alias('a' * max_chars, 'shell pwd')
    with pytest.raises(ValueError, match='cannot exceed 32 characters'):
        manager.add_alias('b' * (max_chars + 1), 'shell pwd')
    assert 'b' * (max_chars + 1) not in manager.aliases['common']
    with pytest.raises(ValueError, match='cannot exceed 32 characters'):
        manager.update_alias('a' * max_chars, 'c' * (max_chars + 1), 'shell ls')
    assert manager.aliases['common']['a' * max_chars] == 'shell pwd'
    manager.update_alias('a' * max_chars, 'd' * max_chars, 'shell ls')
    assert manager.aliases['common']['d' * max_chars] == 'shell ls'
