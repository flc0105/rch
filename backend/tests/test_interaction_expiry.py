"""Expired and stale answers must be distinguishable from invalid active input."""
import threading
from types import SimpleNamespace

import pytest

from server.application.execution.interaction_broker import InteractionBroker, InteractionNotPendingError


def start_preview(timeout=1, task_status=None):
    requests, results = [], []
    published = threading.Event()
    task_status = task_status if task_status is not None else {'status': 'running'}

    def publish(kind, payload, **kwargs):
        if kind == 'interaction_requested':
            requests.append(payload)
            published.set()

    broker = InteractionBroker(SimpleNamespace(publish=publish), SimpleNamespace(get_task=lambda _: task_status))
    thread = threading.Thread(target=lambda: results.append(broker.request(
        task_id='task', client_id='client', tab_id='tab', kind='preview', message='Test',
        preview={}, timeout_seconds=timeout)))
    thread.start()
    assert published.wait(2)
    return broker, requests[0]['interaction_id'], thread, results


def test_expired_preview_reject_and_approve_are_terminal():
    broker, interaction_id, thread, results = start_preview()
    thread.join(3)
    assert not thread.is_alive()
    assert results == [{'status': 'expired', 'value': None}]
    assert broker.pending('tab') == []
    for approved in (False, True):
        with pytest.raises(InteractionNotPendingError, match='not pending'):
            broker.answer(interaction_id, approved=approved)


def test_invalid_active_preview_is_retryable_then_duplicate_reject_is_terminal():
    broker, interaction_id, thread, results = start_preview(timeout=3)
    try:
        with pytest.raises(ValueError, match='Unexpected Preview') as caught:
            broker.answer(interaction_id, approved=True, value={'invalid': True})
        assert not isinstance(caught.value, InteractionNotPendingError)
        assert len(broker.pending('tab')) == 1
        assert broker.answer(interaction_id, approved=False)['status'] == 'rejected'
        with pytest.raises(InteractionNotPendingError):
            broker.answer(interaction_id, approved=False)
    finally:
        thread.join(4)
    assert results == [{'status': 'rejected', 'value': False}]


def test_deadline_passed_before_waiter_removal(monkeypatch):
    from server.application.execution import interaction_broker as module
    broker, interaction_id, thread, results = start_preview(timeout=2)
    try:
        deadline = broker._pending[interaction_id]['deadline']
        monkeypatch.setattr(module.time, 'monotonic', lambda: deadline + 1)
        assert broker.pending('tab') == []
        with pytest.raises(InteractionNotPendingError, match='deadline|not pending'):
            broker.answer(interaction_id, approved=True)
    finally:
        thread.join(3)
    assert results == [{'status': 'expired', 'value': None}]
