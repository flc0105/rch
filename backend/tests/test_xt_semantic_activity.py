"""xt runs one semantic Activity; read-only and internal RPCs stay outside History.

Load the actual class bodies without importing the complete Server stack, which
requires optional Werkzeug in this isolated test environment.
"""
import ast
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.protocol.structured_arg_codec import encode_structured_arg
from core.utils.command_output import (StructuredCommandResult, parse_output_format,
                                       render_structured_result, strip_output_format_arg)
from core.external_tools.install_status import is_installed_status, normalize_install_status
import json

ROOT = Path(__file__).parents[1]


def load_class(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text())
    body = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    assert len(body) == 1
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(path), 'exec'), namespace)
    return namespace[name]


POLICY = load_class('server/application/history/history_record_policy.py',
                    'CommandHistoryRecordPolicy', {})
QUICK_GLOBALS = {
    'CommandHistoryRecordPolicy': POLICY, 're': re,
    'QUICK_TERMINAL_SOURCES': frozenset({'web', 'web_terminal', 'cli'}),
    'QUICK_EXCLUDED_TASK_TYPES': frozenset({'upload', 'remote_file', 'process', 'job_control', 'external_tool'}),
    'QUICK_EXCLUDED_META_FLAGS': frozenset({'quick_action', 'script_run'}),
    'QUICK_MANAGEMENT_PATTERN': re.compile(r'^history(?:\s|$)', re.IGNORECASE),
    'QUICK_REPLAY_PATTERN': re.compile(r'^(?:history\s+run\s+\d+|!\d+)$', re.IGNORECASE),
}
QUICK_POLICY = load_class('server/application/history/quick_history.py',
                          'QuickHistoryRecordPolicy', QUICK_GLOBALS)
ORCH = load_class('server/application/history/history_orchestrator.py',
                  'CommandHistoryOrchestrator', {'threading': threading, 'uuid': uuid,
                                                 'CommandHistoryRecordPolicy': POLICY,
                                                 'QuickHistoryRecordPolicy': QUICK_POLICY})
XT = load_class('server/application/command/builtin_command_support.py',
                'ExternalToolCliBuiltinSupport', {
                    'json': json, 'encode_structured_arg': encode_structured_arg,
                    'parse_output_format': parse_output_format,
                    'strip_output_format_arg': strip_output_format_arg,
                    'StructuredCommandResult': StructuredCommandResult,
                    'render_structured_result': render_structured_result,
                    'normalize_install_status': normalize_install_status,
                    'is_installed_status': is_installed_status,
                })


class Quick:
    def __init__(self):
        self.pending = {}
        self.finished = []

    def begin(self, key, conn, command):
        self.pending[key] = str(command).strip()

    def discard(self, key):
        self.pending.pop(key, None)

    def finish(self, key, status):
        if key in self.pending:
            self.finished.append((self.pending.pop(key), status))


class Store:
    def __init__(self):
        self.quick_store = Quick()
        self.write_service = self
        self.entries = {}

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).isoformat()

    def create_activity_for_dispatch(self, conn, activity_id, pending):
        assert activity_id not in self.entries
        self.entries[activity_id] = {k: pending[k] for k in (
            'kind', 'action', 'origin', 'invocation', 'resolved')}
        self.entries[activity_id].update(status='running', output=[])

    def append_output_for_connection(self, conn, entry_id, status, text, eof=0):
        if entry_id in self.entries:
            self.entries[entry_id]['output'].append((status, text))

    def update_entry_status_for_connection(self, conn, entry_id, status, cwd_end=''):
        if entry_id in self.entries:
            self.entries[entry_id]['status'] = status


class World:
    def __init__(self, *, send_status=1, fail_before=False):
        self.store = Store()
        self.orch = ORCH(self.store)
        self.conn = SimpleNamespace(session_info=SimpleNamespace(
            machine_id='mac', client_id='c1', os_alias='macos', arch='arm64', cwd='/tmp'))
        self.entry = ''
        self.sends = []
        self.send_status = send_status
        self.fail_before = fail_before
        catalog = SimpleNamespace(
            _normalize_platform=lambda s: s, _normalize_arch=lambda s: s,
            list_exec_targets=lambda **kw: [{'exec_name': 'ffmpeg', 'package_id': 'ffmpeg', 'package_key': 'mac'}],
            resolve_exec_target=lambda name, **kw: {'exec_name': name, 'package_id': 'ffmpeg', 'package_key': 'mac'},
        )
        builder = SimpleNamespace(build_client_exec_payload=lambda target, **kw: {
            'exec_name': target['exec_name'], 'package_id': target['package_id'], 'package_key': 'mac',
            'install': {'install_dir': '/tools/ffmpeg'}, 'package': {}, 'raw_args': kw.get('raw_args'),
        })
        assembly = SimpleNamespace(external_tool_catalog_service=catalog,
                                   external_tool_runtime_service=SimpleNamespace(payload_builder=builder))
        self.server = SimpleNamespace(command_history_orchestrator=self.orch,
                                      web_service=SimpleNamespace(assembly=assembly))
        self.xt = XT(self.server, self.conn, self.processor, lambda: self.entry)

    def processor(self):
        def make(command):
            def run():
                self.sends.append(command)
                self.orch.describe_plan(self.entry, {'command_type': 'command', 'command': command})
                if self.fail_before:
                    raise ConnectionError('not sent')
                self.orch.confirm_dispatch(self.conn, self.entry, command)
                if command.startswith('external_tool_install_statuses'):
                    return [(1, '{"items":[{"installed":true}]}')]
                if command.startswith('external_tool_which'):
                    return [(1, '/tools/ffmpeg/bin/ffmpeg')]
                return [(self.send_status, 'program output' if self.send_status else 'exit code 2')]
            return run
        return make

    def execute(self, text, *, parent=None):
        self.entry = self.orch.begin_execution(self.conn, parent or ('xt ' + text), source='cli')
        try:
            events = list(self.xt.xt(text))
            for status, output in events:
                self.orch.append_output(self.conn, self.entry, status, output)
            ok = all(status for status, _ in events)
        except Exception:
            ok = False
            self.orch.finalize_execution(self.conn, self.entry, False)
            raise
        self.orch.finalize_execution(self.conn, self.entry, ok)
        return events


@pytest.mark.parametrize('arg', ['', 'list', 'list --json', '--json', 'info ffmpeg',
                                 'info ffmpeg --json', 'which ffmpeg', 'help', '-h', '--help'])
def test_xt_queries_keep_quick_but_not_activity(arg):
    world = World()
    world.execute(arg)
    assert not world.store.entries
    expected = ('xt ' + arg).strip()
    assert world.store.quick_store.finished == [(expected, 'success')]
    assert not world.orch._pending


@pytest.mark.parametrize('arg', ['list', 'info ffmpeg', 'which ffmpeg', 'help'])
def test_xt_queries_keep_quick_for_web_terminal(arg):
    world = World()
    world.entry = world.orch.begin_execution(world.conn, 'xt ' + arg, source='web')
    events = list(world.xt.xt(arg))
    assert events
    assert not world.store.entries
    world.orch.finalize_execution(world.conn, world.entry, True)
    assert world.store.quick_store.finished == [('xt ' + arg, 'success')]


def test_xt_invalid_query_still_records_failed_quick_without_activity():
    world = World()
    with pytest.raises(ValueError, match='Usage: xt info'):
        world.execute('info')
    assert not world.store.entries
    assert world.store.quick_store.finished == [('xt info', 'error')]


def test_xt_quick_policy_does_not_admit_internal_client_rpc():
    for name in ('xt list', 'xt info ffmpeg', 'xt which ffmpeg', 'xt help', 'xt run ffmpeg', 'xt ffmpeg'):
        assert QUICK_POLICY.should_record(name, source='cli')
    assert not QUICK_POLICY.should_record('external_tool_exec __json__:SENSITIVE', source='cli')
    assert not QUICK_POLICY.should_record('xt list', source='web_api')
    assert not QUICK_POLICY.should_record('history run 7', source='cli')


@pytest.mark.parametrize('arg', ['run ffmpeg -- -version', 'ffmpeg -- -version'])
def test_xt_exec_one_external_tool_activity(arg):
    world = World()
    world.execute(arg)
    assert len(world.sends) == len(world.store.entries) == 1
    entry = next(iter(world.store.entries.values()))
    assert entry['kind'] == 'external_tool' and entry['action'] == 'run_exec'
    assert entry['invocation']['input'] == 'xt ' + arg
    assert entry['invocation']['arguments'] == {'exec_name': 'ffmpeg', 'package_id': 'ffmpeg'}
    assert entry['resolved'] == {'command_type': 'command'}
    assert entry['output'] == [(1, 'program output')]
    assert entry['status'] == 'success'
    assert world.store.quick_store.finished == [('xt ' + arg, 'success')]
    assert '__json__' not in repr(entry) and 'external_tool_exec' not in repr(entry)


def test_xt_exec_nonzero_exits_error_with_one_activity():
    world = World(send_status=0)
    assert world.execute('run ffmpeg -- bad') == [(0, 'exit code 2')]
    assert len(world.store.entries) == 1
    assert next(iter(world.store.entries.values()))['status'] == 'error'


def test_send_failure_creates_no_activity():
    world = World(fail_before=True)
    with pytest.raises(ConnectionError):
        world.execute('run ffmpeg -- -version')
    assert not world.store.entries
    assert world.store.quick_store.finished == [('xt run ffmpeg -- -version', 'error')]


@pytest.mark.parametrize('arg', ['which ffmpeg', 'list --json'])
def test_xt_queries_replayed_through_history_do_not_record(arg):
    world = World()
    world.execute(arg, parent='history run 3')
    assert not world.store.entries and not world.store.quick_store.finished


def test_xt_run_history_replay_is_activity_without_quick_duplicate():
    world = World()
    world.execute('ffmpeg -- -version', parent='history run 2')
    assert len(world.store.entries) == 1
    assert not world.store.quick_store.finished
    assert next(iter(world.store.entries.values()))['action'] == 'run_exec'


def test_internal_external_tool_rpc_cannot_be_recorded_even_if_submitted_directly():
    world = World()
    assert not world.orch.begin_execution(world.conn, 'external_tool_exec __json__:SECRET', source='cli')
    assert not QUICK_POLICY.should_record('external_tool_which __json__:SECRET', source='cli')
    leaked = world.orch.begin_execution(world.conn, 'history run 2', source='cli')
    world.orch.describe_plan(leaked, {'command_type': 'command',
                                      'command': 'external_tool_which __json__:SECRET'})
    world.orch.confirm_dispatch(world.conn, leaked, 'external_tool_which __json__:SECRET')
    assert not world.store.entries and not world.orch._pending


def test_manager_activity_stays_semantic_with_no_rpc_name_in_record():
    world = World()
    aid = world.orch.begin_external_tool_execution(world.conn, 'run_oneshot',
                                                     {'tool_id': 't'}, 'external_tool_oneshot')
    world.orch.confirm_dispatch(world.conn, aid, 'external_tool_oneshot __json__:SECRET')
    assert len(world.store.entries) == 1
    entry = next(iter(world.store.entries.values()))
    assert entry['action'] == 'run_oneshot' and entry['resolved'] == {'command_type': 'command'}
    assert 'external_tool_' not in repr(entry)
