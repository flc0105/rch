"""Opt-in Preview row selection: schema, broker, SDK and original plain approval."""
import threading

import pytest

from client.runtime.sdk import context, interactions
from client.commands.common.services.interaction_service import CommandInteractions, CommandInteractionError
from server.application.execution.interaction_broker import InteractionBroker
from server.application.tasks.task_store import WebTaskStore


def plan(row_ids=True, switches=False):
    preview = {'columns': [{'key': 'label', 'label': 'Item'}],
               'rows': [{'label': 'One'}, {'label': 'Two'}]}
    if row_ids:
        preview['row_ids'] = ['one', 'two']
    if switches:
        preview['switches'] = [{'key': 'force', 'label': 'Force', 'default': False}]
    return preview


@pytest.mark.parametrize('bad_ids', [[], ['one'], ['one','one'], ['one', 1], ['a b','c'],
                                      ['../bad','two'], ['-bad','two'], 'one'])
def test_reject_bad_ids(bad_ids):
    with pytest.raises(ValueError, match='row|ID'):
        InteractionBroker._normalize_preview({**plan(), 'row_ids': bad_ids})


def test_existing_previews_unchanged():
    assert 'row_ids' not in InteractionBroker._normalize_preview(plan(False))
    assert InteractionBroker._normalize_preview(plan())['row_ids'] == ['one','two']


class Events:
    def __init__(self):
        self.ready = threading.Event()
        self.payload = None
    def publish(self, kind, data, target_tab_id=''):
        if kind == 'interaction_requested':
            self.payload = data
            self.ready.set()


@pytest.mark.parametrize('with_switch', [False, True])
def test_broker_replies_validate_ids_and_switches(with_switch):
    events = Events()
    store = WebTaskStore()
    task = store.create_task('client-A', 'script test', tab_id='tab-A')
    broker = InteractionBroker(events, store)
    results = []
    worker = threading.Thread(target=lambda: results.append(broker.request(
        task_id=task['task_id'], client_id='client-A', tab_id='tab-A',
        kind='preview', message='Select', preview=plan(switches=with_switch), timeout_seconds=5)), daemon=True)
    worker.start()
    assert events.ready.wait(2)
    req = events.payload
    assert req['preview']['row_ids'] == ['one', 'two']
    assert broker.pending('tab-A')[0]['preview']['row_ids'] == ['one', 'two']
    valid = {'selected_rows': ['two']}
    if with_switch:
        valid['force'] = False
    for bad in (
        None, True, [], {'selected_rows': ['other']}, {'selected_rows': ['one','one']},
        {'selected_rows': [1]}, {'selected_rows': 'one'},
        {**valid, 'unknown': True},
        ({'selected_rows': ['one'], 'force': 1} if with_switch else {}),
    ):
        with pytest.raises(ValueError):
            broker.answer(req['interaction_id'], approved=True, value=bad)
    assert worker.is_alive()
    broker.answer(req['interaction_id'], approved=True, value=valid)
    worker.join(2)
    assert results == [{'status': 'answered', 'value': valid}]


def test_empty_selection_is_approved_but_not_rejected():
    events = Events()
    store = WebTaskStore()
    task = store.create_task('client-B', 'script', tab_id='tab-B')
    broker = InteractionBroker(events, store)
    results = []
    worker = threading.Thread(target=lambda: results.append(broker.request(
        task_id=task['task_id'], client_id='client-B', tab_id='tab-B',
        kind='preview', message='Test', preview=plan(), timeout_seconds=5)), daemon=True)
    worker.start()
    assert events.ready.wait(2)
    broker.answer(events.payload['interaction_id'], approved=True, value={'selected_rows': []})
    worker.join(2)
    assert results[0]['value'] == {'selected_rows': []}


def test_sdk_selection_returns_ids_and_rejects(monkeypatch):
    class API:
        response = {'status': 'answered', 'value': {'selected_rows': ['two']}}
        def post_data(self, url, **kw):
            assert kw['json']['preview'].get('row_ids') in (['one', 'two'], None)
            return self.response
    monkeypatch.setattr(interactions, 'ClientApiClient', API)
    monkeypatch.setattr(context, 'get_script_grant_token', lambda: 'test-grant')
    monkeypatch.setattr(context, 'get_command_id', lambda: 42)
    assert context.select_preview_rows('Choose', plan()) == ['two']
    API.response = {'status': 'answered', 'value': {'selected_rows': []}}
    assert interactions.select_preview_rows('Choose', plan()) == []
    API.response = {'status': 'rejected', 'value': False}
    with pytest.raises(interactions.ScriptSdkInteractionError):
        context.select_preview_rows('Choose', plan())
    API.response = {'status': 'answered', 'value': True}
    assert interactions.approve_preview('Plain', plan(False)) is True


def test_client_command_row_helper(monkeypatch):
    from client.commands.common.services import interaction_service
    monkeypatch.setattr(CommandInteractions, 'request', lambda self, *a, **kw:
                        {'status': 'answered', 'value': {'selected_rows': ['one']}})
    assert CommandInteractions(object()).select_preview_rows('Test', plan()) == ['one']
    monkeypatch.setattr(CommandInteractions, 'request', lambda self, *a, **kw:
                        {'status': 'rejected', 'value': False})
    with pytest.raises(CommandInteractionError):
        CommandInteractions(object()).select_preview_rows('Test', plan())


def test_selected_rows_reserved_switch_key_rejected():
    offered = plan(switches=True)
    offered['switches'][0]['key'] = 'selected_rows'
    with pytest.raises(ValueError, match='conflict'):
        InteractionBroker._normalize_preview(offered)


def test_script_library_smoke_executes_without_deleting(monkeypatch, capsys):
    from core.utils.script_metadata import read_script_metadata_from_file
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / 'scripts/test/interaction/test_preview_rows.py'
    metadata = read_script_metadata_from_file(str(script))
    assert metadata['name'] == 'test/interaction/test_preview_rows'
    assert metadata['api_grants'] == ['interactions:request']
    assert metadata['params'][0]['type'] == 'string'
    monkeypatch.setattr(context, 'select_preview_rows',
                        lambda *args, **kwargs: ['second'])
    exec(compile(script.read_text(), str(script), 'exec'), {'kwargs': {}})
    output = capsys.readouterr().out
    assert 'SELECTED: second' in output
    assert 'PASS: no changes performed' in output
