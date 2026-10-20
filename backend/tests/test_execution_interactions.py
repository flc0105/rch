"""First-phase RCH Command/Script interactive approval regression tests."""
import threading
import time
from types import SimpleNamespace

import pytest

from server.application.execution.interaction_broker import InteractionBroker
from server.application.tasks.task_store import WebTaskStore
from server.application.auth.script_grant_policy import ScriptGrantPolicy
from server.application.auth.script_grant_service import ScriptGrantService
from client.runtime.sdk import interactions


class Events:
    def __init__(self):
        self.events = []
        self.ready = threading.Event()

    def publish(self, kind, payload, target_tab_id=''):
        self.events.append((kind, payload, target_tab_id))
        self.ready.set()


@pytest.fixture
def broker_case():
    bus = Events()
    store = WebTaskStore()
    task = store.create_task('client-A', 'test-interaction', tab_id='tab-A')
    return InteractionBroker(bus, store), bus, store, task


def run_request_in_thread(broker, task, *, kind='confirm', timeout_seconds=5):
    answer = {}

    def run():
        answer['result'] = broker.request(
            task_id=task['task_id'], client_id='client-A', tab_id='tab-A',
            kind=kind, title='Test', message='Approve?', timeout_seconds=timeout_seconds,
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, answer


def wait_for_request(bus):
    assert bus.ready.wait(2)
    return next(event[1] for event in bus.events if event[0] == 'interaction_requested')


def test_explicit_approval_only_and_pending_recovery(broker_case):
    broker, bus, store, task = broker_case
    thread, result = run_request_in_thread(broker, task)
    item = wait_for_request(bus)
    assert [x['interaction_id'] for x in broker.pending('tab-A')] == [item['interaction_id']]
    assert broker.pending('unrelated-tab') == []
    assert thread.is_alive()
    broker.answer(item['interaction_id'], approved=True)
    thread.join(timeout=2)
    assert result['result'] == {'status': 'answered', 'value': True}
    assert broker.pending('tab-A') == []
    with pytest.raises(ValueError, match='not pending'):
        broker.answer(item['interaction_id'], approved=True)


def test_reject_and_timeout_fail_closed(broker_case):
    broker, bus, store, task = broker_case
    thread, result = run_request_in_thread(broker, task)
    item = wait_for_request(bus)
    broker.answer(item['interaction_id'], approved=False)
    thread.join(timeout=2)
    assert result['result'] == {'status': 'rejected', 'value': False}
    result2 = broker.request(task_id=task['task_id'], client_id='client-A',
                             tab_id='tab-A', kind='confirm', message='danger', timeout_seconds=1)
    assert result2['status'] == 'expired'
    assert result2['value'] is None


def test_text_input_empty_allowed_and_max_length_enforced(broker_case):
    broker, bus, store, task = broker_case
    thread, result = run_request_in_thread(broker, task, kind='input')
    item = wait_for_request(bus)
    with pytest.raises(ValueError, match='4096'):
        broker.answer(item['interaction_id'], approved=True, value='x' * 4097)
    assert thread.is_alive()
    broker.answer(item['interaction_id'], approved=True, value='')
    thread.join(timeout=2)
    assert result['result'] == {'status': 'answered', 'value': ''}


def test_task_cancel_unblocks_pending_interaction(broker_case):
    broker, bus, store, task = broker_case
    thread, result = run_request_in_thread(broker, task)
    wait_for_request(bus)
    store.request_cancel(task['task_id'])
    thread.join(timeout=2)
    assert result['result']['status'] == 'cancelled'


def test_single_pending_per_task(broker_case):
    broker, bus, store, task = broker_case
    thread, result = run_request_in_thread(broker, task)
    item = wait_for_request(bus)
    with pytest.raises(ValueError, match='already has'):
        broker.request(task_id=task['task_id'], client_id='client-A', tab_id='tab-A',
                       kind='input', message='second')
    broker.answer(item['interaction_id'], approved=False)
    thread.join(timeout=2)


def test_grant_requires_interaction_scope_and_correct_identity():
    grant_service = ScriptGrantService()
    session = SimpleNamespace(session_info=SimpleNamespace(client_id='client-A', hostname='test', machine_id='abc'))
    issued = grant_service.issue_script_grant(
        session=session, command_id=19,
        grant_request={'script_name': 'common/test/interaction_example', 'api_grants': ['interactions:request']},
    )
    token = issued['token']
    assert grant_service.authorize_request(method='POST', path='/api/interactions/client/request',
                                           headers={'X-Script-Grant-Token': token})
    assert grant_service.get_interaction_identity(token) == {'client_id': 'client-A', 'command_id': 19}
    assert grant_service.get_interaction_identity('wrong') is None
    assert grant_service.policy.match_request_scope('POST', '/api/interactions/client/request') == 'interactions:request'
    grant_service.revoke_by_command(client_id='client-A', command_id=19)
    assert grant_service.get_interaction_identity(token) is None


def test_client_sdk_yes_no_and_ask(monkeypatch):
    calls = []

    class FakeClient:
        def post_data(self, path, **kwargs):
            calls.append((path, kwargs))
            return {'status': 'answered', 'value': 'abc'} if kwargs['json']['kind'] == 'input' else {'status': 'answered', 'value': True}

    monkeypatch.setattr(interactions, 'ClientApiClient', FakeClient)
    monkeypatch.setattr(interactions.context, 'get_script_grant_token', lambda: 'token')
    monkeypatch.setattr(interactions.context, 'get_command_id', lambda: 4)
    assert interactions.confirm('safe?') is True
    assert interactions.ask('label?') == 'abc'
    assert calls[0][1]['json']['kind'] == 'confirm'
    assert calls[1][1]['json']['kind'] == 'input'
    monkeypatch.setattr(interactions, 'ClientApiClient', lambda: SimpleNamespace(post_data=lambda *a, **kw: {'status': 'expired', 'value': None}))
    assert interactions.confirm('safe?') is False
    with pytest.raises(interactions.ScriptSdkInteractionError):
        interactions.ask('label?')


def test_script_interaction_requires_explicit_grant(monkeypatch):
    monkeypatch.setattr(interactions.context, 'get_script_grant_token', lambda: '')
    with pytest.raises(interactions.ScriptSdkInteractionError, match='api_grants'):
        interactions.confirm('ok?')


def test_secret_answer_never_appears_in_sse_or_pending(broker_case):
    broker, bus, store, task = broker_case
    thread, result = run_request_in_thread(broker, task, kind='secret')
    item = wait_for_request(bus)
    broker.answer(item['interaction_id'], approved=True, value='secret-value')
    thread.join(timeout=2)
    assert result['result']['value'] == 'secret-value'
    assert all('secret-value' not in str(e) for e in bus.events)


def test_root_facade_exposes_the_assembled_interaction_dependencies(monkeypatch):
    """Startup routes and interactive builtins must share assembly-owned instances."""
    import importlib.util
    import sys
    from pathlib import Path
    from types import ModuleType

    class AssemblyStub:
        def __init__(self):
            self.event_bus = Events()
            self.script_grant_service = ScriptGrantService()
            self.task_store = WebTaskStore()
            self.interaction_broker = InteractionBroker(self.event_bus, self.task_store)

        def __getattr__(self, name):
            if name.endswith('_api'):
                return SimpleNamespace()
            raise AttributeError(name)

    # The facade needs only the assembly contract; avoid unrelated Flask imports.
    assembly_module = ModuleType('server.application.assembly')
    assembly_module.ServerApplicationAssembly = AssemblyStub
    facade_file = Path(__file__).resolve().parents[1] / 'server/application/app_facade.py'
    with monkeypatch.context() as patched:
        patched.setitem(sys.modules, 'server.application.assembly', assembly_module)
        spec = importlib.util.spec_from_file_location('_interaction_facade_under_test', facade_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assembly = AssemblyStub()
        service = module.ServerWebService(server=SimpleNamespace(), assembly=assembly)

    assert service.task_store is assembly.task_store
    assert service.interaction_broker is assembly.interaction_broker
    assert service.interaction_broker.task_store is service.task_store
