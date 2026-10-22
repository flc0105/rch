"""Job user operations create semantic Activity; internal job_control stays internal.

Isolated actual-class tests do not import the optional Flask/Werkzeug stack.
"""
import ast
import json
import sqlite3
import threading
from contextlib import contextmanager
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.utils.job_control_result import encode_job_control_result, decode_job_control_result
from client.jobs.command_control import ClientJobControl

ROOT = Path(__file__).parents[1]


def load_class(path, name, globals_):
    tree = ast.parse((ROOT / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), 'exec'), globals_)
    return globals_[name]


POLICY = load_class('server/application/history/history_record_policy.py', 'CommandHistoryRecordPolicy', {})
QUICK = load_class('server/application/history/quick_history.py', 'QuickHistoryRecordPolicy', {
    'CommandHistoryRecordPolicy': POLICY,
    'QUICK_TERMINAL_SOURCES': {'cli', 'web', 'web_terminal'},
    'QUICK_EXCLUDED_TASK_TYPES': {'upload', 'remote_file', 'process', 'job_control', 'external_tool'},
    'QUICK_EXCLUDED_META_FLAGS': {'quick_action', 'script_run'},
    'QUICK_MANAGEMENT_PATTERN': __import__('re').compile(r'^history(?:\s|$)', __import__('re').I),
    'QUICK_REPLAY_PATTERN': __import__('re').compile(r'^(?:history\s+run\s+\d+|!\d+)$', __import__('re').I),
})
ORCH = load_class('server/application/history/history_orchestrator.py', 'CommandHistoryOrchestrator', {
    'CommandHistoryRecordPolicy': POLICY, 'QuickHistoryRecordPolicy': QUICK,
    'uuid': uuid, 'threading': threading, 'shlex': __import__('shlex'),
})
JOB = load_class('server/application/command/job_builtin_support.py', 'JobBuiltinSupport', {
    'json': json, 'shlex': __import__('shlex'), 'decode_job_control_result': decode_job_control_result,
    'COMMAND_TYPE_JOB_CONTROL': 'job_control',
    'visible_on_platform': lambda item, platform: True,
})
WEB = load_class('server/application/jobs/background_job_service.py', 'BackgroundJobService', {
    'json': json, 'threading': threading,
    'COMMAND_TYPE_JOB_CONTROL': 'job_control',
    'decode_job_control_result': decode_job_control_result,
    'normalize_job_execution_mode': lambda mode, default='inproc': mode or default,
})
WRITE = load_class('server/application/history/history_write_service.py', 'HistoryWriteService', {})
from core.utils.json_utils import compact_json_dumps, json_loads_typed
STORE = load_class('server/application/history/history_store.py', 'CommandHistoryStore', {
    'compact_json_dumps': compact_json_dumps, 'json_loads_typed': json_loads_typed,
    'COMMAND_HISTORY_MAX_OUTPUT_RECORD_CHARS': 20000, 'COMMAND_HISTORY_MAX_OUTPUT_RECORDS': 50,
})


class Quick:
    def __init__(self):
        self.pending, self.saved = {}, []
    def begin(self, key, conn, command):
        self.pending[key] = command
    def finish(self, key, status):
        if key in self.pending:
            self.saved.append((self.pending.pop(key), status))
    def discard(self, key):
        self.pending.pop(key, None)


class Store:
    def __init__(self):
        self.quick_store = Quick()
        self.entries = {}
        self.updated = []
        self.write_service = self
        self._lock = threading.RLock()
    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).isoformat()
    def create_activity_for_dispatch(self, conn, key, record):
        assert key not in self.entries
        self.entries[key] = {'kind': record['kind'], 'action': record['action'],
                             'resolved': record['resolved'].copy(),
                             'invocation': record['invocation'].copy(), 'status': 'running'}
    def set_background_job_result(self, conn, key, result):
        if key in self.entries:
            self.entries[key]['resolved'].update({k:result[k] for k in ('job_id','total','succeeded','failed') if k in result})
    def update_entry_status_for_connection(self, conn, key, status, **kwargs):
        if key in self.entries:
            self.entries[key]['status'] = status
    def append_output_for_connection(self, conn, key, *args):
        pass


@pytest.fixture
def env():
    store = Store()
    orch = ORCH(store)
    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='c1', machine_id='m1', os_alias='linux'))
    def stream_command(session, command, **kwargs):
        assert session is conn and kwargs['command_type'] == 'job_control'
        if kwargs.get('history_entry_id'):
            orch.confirm_dispatch(conn, kwargs['history_entry_id'], command, 'job_control')
        action = json.loads(command)['action']
        if action == 'start':
            yield (1, 'Fetching job: example')
            yield (1, encode_job_control_result('start', 'Background job started: example', job_id='j123'))
        elif action == 'stop_all':
            yield (0, encode_job_control_result('stop_all', 'Stop requested for 1 of 2; 1 failed',
                                               total=2, succeeded=1, job_ids=['j123'], errors=['j456 failed']))
        elif action == 'stop':
            yield (1, encode_job_control_result('stop', 'Stop request sent: example', job_id='j123'))
        else:
            yield (1, 'No jobs running')
    remote = SimpleNamespace(stream_command=stream_command)
    job_api = SimpleNamespace(
        prepare_background_job_start=lambda cid,name,mode: mode or 'inproc',
        list_background_job_catalog=lambda cid: [{'job_name':'example'}],
        background_job_service=SimpleNamespace(_build_job_control_command=lambda action,**kw:json.dumps({'action':action,**kw})),
    )
    server = SimpleNamespace(command_history_orchestrator=orch, web_service=SimpleNamespace(job_api=job_api))
    return orch, store, conn, server, remote


@pytest.mark.parametrize('query', ['job list','job ps','job status example'])
def test_job_queries_only_quick(env, query):
    orch, store, conn, server, remote = env
    eid=orch.begin_execution(conn,query,'cli')
    builtin=JOB(server,conn,remote,lambda:eid)
    assert list(builtin.job(query.removeprefix('job ')))[-1][0] == 1
    orch.finalize_execution(conn,eid,True)
    assert store.quick_store.saved == [(query,'success')]
    assert not store.entries


@pytest.mark.parametrize('command,action', [('job start example','start_job'),('job stop example','stop_job'),('job stop-all','stop_all_jobs')])
def test_job_operations_one_activity_and_quick(env, command, action):
    orch, store, conn, server, remote = env
    eid=orch.begin_execution(conn,command,'cli')
    builtin=JOB(server,conn,remote,lambda:eid)
    events=list(builtin.job(command.removeprefix('job ')))
    assert '__json__' not in str(events)
    assert all('"job_id"' not in str(i) for i in events)
    assert list(store.entries)==[eid]
    assert store.entries[eid]['kind']=='background_job'
    assert store.entries[eid]['action']==action
    assert store.entries[eid]['resolved']['command_type']=='job_control'
    assert 'command' not in store.entries[eid]['resolved']
    assert store.entries[eid]['resolved']['job_id']=='j123' if action != 'stop_all_jobs' else store.entries[eid]['resolved']['failed']==1
    orch.finalize_execution(conn,eid,events[-1][0]==1)
    assert store.quick_store.saved == [(command, 'success' if events[-1][0] else 'error')]


def test_web_start_semantic_and_no_quick(env):
    orch, store, conn, server, remote = env
    def get_connection(cid):
        return conn
    def stream_foreground_command(cid,cmd,**kw):
        yield from remote.stream_command(conn,cmd,**{k:v for k,v in kw.items() if k in {'command_type','history_entry_id'}})
    svc=WEB(None,None,SimpleNamespace(get_connection=get_connection, stream_foreground_command=stream_foreground_command),None,server=server)
    text=svc.start_job('c1','example',params={'secret':'DO_NOT_STORE'},origin='web_ui')['message']
    assert text=='Fetching job: example\nBackground job started: example'
    entry=next(iter(store.entries.values()))
    assert entry['kind']=='background_job' and entry['action']=='start_job'
    assert entry['resolved']['job_id']=='j123'
    assert 'secret' not in json.dumps(entry)
    assert store.quick_store.saved==[]


def test_client_stop_all_partial_structured():
    manager=SimpleNamespace(stop_all_jobs=lambda:{'total':2,'stopped':[{'display_name':'a','job_id':'a-id'}], 'errors':['b failed']})
    commands=SimpleNamespace(socket=SimpleNamespace(runtime=SimpleNamespace(job_manager=manager)))
    status,text=ClientJobControl.execute(commands,'{"action":"stop_all"}')
    result=decode_job_control_result(text,'stop_all')
    assert status==0 and result['succeeded']==1 and result['failed']==1
    assert result['job_ids']==['a-id']


def test_job_control_alone_not_activity(env):
    orch,store,conn,server,remote=env
    eid=orch.begin_execution(conn,'job ps',source='cli')
    orch.confirm_dispatch(conn,eid,'{"action":"ps"}','job_control')
    assert not store.entries


def test_send_failure_leaves_no_activity(env):
    orch,store,conn,server,remote=env
    eid=orch.begin_execution(conn,'job start example',source='cli')
    def failing(*args,**kwargs):
        raise OSError('not sent')
    builtin=JOB(server,conn,SimpleNamespace(stream_command=failing),lambda:eid)
    with pytest.raises(OSError):
        list(builtin.job('start example'))
    orch.finalize_execution(conn,eid,False)
    assert not store.entries


def test_cli_job_params_not_copied_into_activity(env):
    orch,store,conn,server,remote=env
    command = "job start example --params SENSITIVE"
    eid=orch.begin_execution(conn,command,'cli')
    # The pending intent contains raw text before the Job builtin promotes it.
    orch.begin_background_job_execution(conn,'start_job',{'job_name':'example'},origin='cli',entry_id=eid)
    orch.confirm_dispatch(conn,eid,'{"action":"start","params":{"secret":"SENSITIVE"}}','job_control')
    assert 'SENSITIVE' not in json.dumps(store.entries[eid])
    orch.finalize_execution(conn,eid,True)
    assert store.quick_store.saved == [(command,'success')]


def test_manager_stop_all_reports_partial_without_losing_successes():
    from client.jobs.core.manager import JobManager
    manager = object.__new__(JobManager)
    manager._lock = threading.RLock()
    a = SimpleNamespace(job_id='a-id', display_name='a')
    b = SimpleNamespace(job_id='b-id', display_name='b')
    manager._runtimes = {'a': a, 'b': b}
    manager.cleanup_finished_jobs = lambda: None
    manager._request_runtime_stop = lambda runtime, notify: (_ for _ in ()).throw(RuntimeError('denied')) if runtime is b else None
    report = manager.stop_all_jobs()
    assert report == {'total':2, 'stopped':[{'job_id':'a-id','display_name':'a'}], 'errors':['b: denied']}


def test_job_result_no_raw_payload_or_source(env):
    orch, store, conn, server, remote = env
    eid = orch.begin_execution(conn,'job start example','cli')
    builtin = JOB(server,conn,remote,lambda:eid)
    events = list(builtin.job('start example'))
    assert any('Background job started' in str(event[1]) for event in events)
    assert not any('"action":"start"' in str(event[1]) for event in events)
    entry = store.entries[eid]
    assert entry['resolved']['job_id'] == 'j123'
    assert 'params' not in json.dumps(entry)


@pytest.mark.parametrize('action,result,expected', [
    ('stop_all_jobs', {'total': 2, 'succeeded': 2, 'failed': 0,
                       'job_ids': ['first-id', 'second-id'], 'errors': []},
     {'command_type': 'job_control', 'total': 2, 'succeeded': 2, 'failed': 0,
      'job_ids': ['first-id', 'second-id'], 'errors': []}),
    ('start_job', {'job_id': 'actual-id'},
     {'command_type': 'job_control', 'job_id': 'actual-id'}),
])
def test_background_job_counts_persist_in_real_sqlite(action, result, expected):
    """Catch updates that mutate resolved in memory but omit resolved_json in SQL."""
    sql = sqlite3.connect(':memory:')
    sql.row_factory = sqlite3.Row
    fields = (
        'activity_id', 'machine_id', 'client_id', 'kind', 'action', 'origin',
        'presentation', 'status', 'invocation_json', 'resolved_json',
        'result_json', 'created_at', 'started_at', 'finished_at', 'files_json',
    )
    sql.execute('CREATE TABLE activity_records (' + ','.join(f'{field} TEXT' for field in fields) + ')')
    row = {
        'activity_id': 'a1', 'machine_id': 'm1', 'client_id': 'c1',
        'kind': 'background_job', 'action': action, 'origin': 'cli',
        'presentation': 'terminal', 'status': 'running', 'invocation_json': '{}',
        'resolved_json': '{"command_type":"job_control"}',
        'result_json': '{"output_records":[]}', 'created_at': '',
        'started_at': '', 'finished_at': None, 'files_json': '[]',
    }
    sql.execute('INSERT INTO activity_records VALUES (' + ','.join('?' for _ in fields) + ')',
                [row[field] for field in fields])

    class Database:
        def connection(self):
            return sql

        @contextmanager
        def transaction(self):
            with sql:
                yield sql

    store = object.__new__(STORE)
    store.database = Database()
    store._lock = threading.RLock()
    conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='m1'))
    WRITE(store).set_background_job_result(conn, 'a1', result)
    resolved = json.loads(sql.execute(
        'SELECT resolved_json FROM activity_records WHERE activity_id = ?', ('a1',),
    ).fetchone()['resolved_json'])
    assert resolved == expected
    sql.close()
