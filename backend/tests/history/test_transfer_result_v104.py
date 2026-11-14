"""Transfer Activity snapshots use standard Result events; file bytes stay on Transfer."""
from types import SimpleNamespace
from server.application.history.lifecycle_adapter import LifecycleAdapter


class FakeCoordinator:
    def __init__(self):
        self.events = []
        self.outputs = []
        self.finishes = []
        self.history_store = SimpleNamespace(artifact_service=None)

    def prepare(self, *_args, **_kwargs):
        return 'activity-1'

    def dispatch(self, *_args, **_kwargs):
        return None

    def append_result_event(self, _conn, _entry_id, event):
        self.events.append(event)

    def append_output(self, _conn, _entry_id, ok, message, **_kwargs):
        self.outputs.append((ok, message))

    def finish(self, _conn, _entry_id, ok, **kwargs):
        self.finishes.append((ok, kwargs.get('status')))


def test_transfer_activity_progress_and_completed_preserves_visible_output():
    coordinator = FakeCoordinator()
    adapter = LifecycleAdapter(coordinator)
    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='client1'))
    transfer = {'transfer_id': 'transfer1', 'direction': 'server_to_client',
                'filename': 'sample.txt', 'state': 'running', 'total_bytes': 100,
                'transferred_bytes': 0, 'metadata': {'source': 'remote_file_upload'}}
    adapter.bind_transfer_service(SimpleNamespace(get_transfer=lambda _id: transfer))
    assert adapter._transfer_dispatched(conn, {'transfer_id': 'transfer1'})
    assert [e['event_type'] for e in coordinator.events] == ['started']
    for amount in (1, 12, 15, 50, 100):
        adapter.transfer_updated({**transfer, 'transferred_bytes': amount})
    assert len([e for e in coordinator.events if e['event_type'] == 'progress']) == 3
    adapter.transfer_updated({**transfer, 'state': 'completed', 'transferred_bytes': 100})
    assert coordinator.events[-1]['event_type'] == 'completed'
    assert coordinator.events[-1]['status'] == 'success'
    assert len([e for e in coordinator.events if e['event_type'] == 'completed']) == 1
    assert coordinator.outputs == [(1, 'Transferred sample.txt (100 bytes)')]
    assert coordinator.finishes == [(True, 'success')]
    adapter.transfer_updated({**transfer, 'state': 'completed'})
    assert len([e for e in coordinator.events if e['event_type'] == 'completed']) == 1


def test_transfer_fail_and_interrupt_have_single_terminal_result():
    for final_state, expected_status in [('failed', 'error'), ('cancelled', 'cancelled')]:
        coordinator = FakeCoordinator()
        adapter = LifecycleAdapter(coordinator)
        conn = SimpleNamespace(session_info=SimpleNamespace(client_id='client1'))
        transfer = {'transfer_id': 'transfer2', 'direction': 'server_to_client',
                    'filename': 'sample.txt', 'state': 'running', 'total_bytes': None,
                    'metadata': {'source': 'remote_file_upload'}}
        adapter.bind_transfer_service(SimpleNamespace(get_transfer=lambda _id: transfer))
        adapter._transfer_dispatched(conn, {'transfer_id': 'transfer2'})
        adapter.transfer_updated({**transfer, 'state': final_state, 'error': 'Access denied' if final_state == 'failed' else ''})
        assert coordinator.events[-1]['status'] == expected_status
        assert len([e for e in coordinator.events if e['event_type'] == 'completed']) == 1
