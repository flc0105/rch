"""Optional preview switches, fail-closed approval and Server builtin ownership."""
import threading
import time
from types import SimpleNamespace

import pytest

from client.commands.common.mixins.process_ops import CommandProcessMixin
from client.commands.common.services.process import approved_process_service as aps
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.application.execution.interaction_broker import InteractionBroker
from server.application.tasks.task_store import WebTaskStore


class Events:
    def __init__(self):
        self.ready = threading.Event()
        self.events = []

    def publish(self, kind, data, target_tab_id=''):
        self.events.append((kind, data, target_tab_id))
        if kind == 'interaction_requested':
            self.ready.set()


def preview():
    return aps.build_multi_preview([{
        'pid': 2233, 'name': 'example', 'user': 'user', 'exec_path': '/usr/bin/example',
        'created_at': 1.0, 'cmdline': ['/usr/bin/example'], 'cwd': '/tmp',
        'ppid': 1, 'status': 'running', 'memory_rss': 100, 'threads': 1,
        'listening': [{'protocol': 'tcp', 'address': '127.0.0.1', 'port': 8080}],
    }], criteria={'port':8080})


def test_preview_switch_schema_is_optional_and_strict():
    normal = InteractionBroker._normalize_preview({'summary': [], 'columns': [], 'rows': [], 'details': []})
    assert 'switches' not in normal
    enriched = InteractionBroker._normalize_preview(preview())
    assert enriched['switches'] == [{
        'key': 'force', 'label': 'Force termination (SIGKILL / -9)',
        'description': 'OFF: SIGTERM. ON: immediate SIGKILL.',
        'default': False,
    }]
    for switches in (
        [{'key': 'force', 'label': 'Force', 'default': 'yes'}],
        [{'key': 'force', 'label': 'Force'}, {'key': 'force', 'label': 'Again'}],
        [{'key': 'force', 'label': 'Force', 'html': '<img>'}],
        [{'key': 'bad-key', 'label': 'Force'}],
        'force',
    ):
        with pytest.raises(ValueError):
            InteractionBroker._normalize_preview({'switches': switches})


@pytest.mark.parametrize('approve,force', [(True, False), (True, True), (False, None)])
def test_broker_round_trip_validated_switches(approve, force):
    events = Events()
    store = WebTaskStore()
    task = store.create_task('client-A', 'kill_port 8080', tab_id='tab-A')
    broker = InteractionBroker(events, store)
    result = []
    worker = threading.Thread(target=lambda: result.append(broker.request(
        task_id=task['task_id'], client_id='client-A', tab_id='tab-A',
        kind='preview', message='Kill process?', preview=preview(), timeout_seconds=5)), daemon=True)
    worker.start()
    assert events.ready.wait(2)
    offered = events.events[-1][1]
    assert offered['preview']['switches'][0]['default'] is False
    assert broker.pending('tab-A')[0]['preview']['switches'] == offered['preview']['switches']
    if approve:
        for forged in ({'force': 'true'}, {'force': 1}, {}, {'force': False, 'extra': True}, True, None):
            with pytest.raises(ValueError, match='switch'):
                broker.answer(offered['interaction_id'], approved=True, value=forged)
        assert worker.is_alive(), 'invalid input must not release waiting task'
    broker.answer(offered['interaction_id'], approved=approve, value={'force': force, 'selected_rows': ['2233']} if approve else None)
    worker.join(2)
    assert not worker.is_alive()
    assert result[0]['status'] == ('answered' if approve else 'rejected')
    assert result[0]['value'] == ({'force': force, 'selected_rows':['2233']} if approve else False)


def test_client_process_signal_only_follows_approved_switch(monkeypatch):
    rows=[{'pid':2233,'name':'example','user':'user','exec_path':'/usr/bin/example',
           'created_at':1.0,'cmdline':[],'cwd':'/tmp','ppid':1,'status':'running',
           'memory_rss':0,'threads':1,'listening':[]}]
    monkeypatch.setattr(aps,'find_targets',lambda *a,**kw:rows)
    calls=[]
    monkeypatch.setattr(aps,'terminate_verified',lambda row,**kw:(calls.append(kw),
                           'SIGKILL' if kw['force'] else 'SIGTERM')[1])
    owner=SimpleNamespace(_set_timeout=lambda *a:None,_checkpoint=lambda **k:None)
    for force in (False,True):
        monkeypatch.setattr(aps.ClientCommandInteractions,'approve_processes',lambda *a:({'2233'},force))
        status,msg=CommandProcessMixin._acmd_kill(owner,{'port':8080,'force':False})
        assert status==1 and ('SIGKILL' if force else 'SIGTERM') in msg
    assert calls==[{'force':False,'port':8080},{'force':True,'port':8080}]


def test_broker_rows_and_switches_validate_exact_selection():
    offered=InteractionBroker._normalize_preview(preview())
    assert offered['row_ids']==['2233']
    assert offered['switches'][0]['key']=='force'
    assert offered['row_details'][0]['row_id']=='2233'
