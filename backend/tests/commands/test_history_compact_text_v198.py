"""Preserve the old readable Quick History while keeping the JSON contract."""
import os
import subprocess
import sys
from pathlib import Path


def test_history_compact_text_and_json_contract(tmp_path):
    root = Path(__file__).resolve().parents[3]
    code = r'''
import json, sys, types
from types import SimpleNamespace
config = types.ModuleType('server.config.config')
config.SCRIPT_PATH = 'backend/server/resources/scripts'
config.COMMAND_HISTORY_RECENT_LIMIT = 100
sys.modules['server.config.config'] = config
from server.application.command.builtin_command_support import HistoryBuiltinSupport
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
class Store:
    def get_history_for_connection(self, _):
        return [
            {'command': 'shell echo a very very very very very long command', 'is_pinned': True},
            {'command': 'whoami', 'is_pinned': False},
        ]
support = HistoryBuiltinSupport(Store(), SimpleNamespace(), lambda: None, lambda: None)
reg = SERVER_COMMAND_REGISTRY
text = list(support.history(reg.parse_invocation('history', 'list')))
assert text == [(1, '  1  shell echo a very very very very very long command\n'
                    '  2  whoami\n\n'
                    'Tip: use history run <index> or !<index> to run a history item quickly')], text
pinned = list(support.history(reg.parse_invocation('history', 'list -p')))
assert pinned == [(1, '  1  shell echo a very very very very very long command\n\n'
                      'Tip: use history run <index> or !<index> to run a history item quickly')], pinned
structured = json.loads(list(support.history(reg.parse_invocation('history', 'list --json')))[0][1])
assert structured == [
    {'index': 1, 'command': 'shell echo a very very very very very long command', 'pinned': True},
    {'index': 2, 'command': 'whoami', 'pinned': False},
]
print('HISTORY_TEXT_OK')
'''
    finished = subprocess.run([sys.executable, '-c', code], cwd=root,
        env={**os.environ, 'PYTHONPATH': str(root / 'backend')},
        capture_output=True, text=True)
    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert 'HISTORY_TEXT_OK' in finished.stdout
