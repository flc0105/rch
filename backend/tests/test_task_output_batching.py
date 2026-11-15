"""Web task output batching retains exact chunks and completion ordering."""

import time
import asyncio
import unittest
from types import SimpleNamespace

from server.application.tasks.task_runner import WebTaskRunner, _TaskResultBatch
from server.application.command.command_execution_event import CommandExecutionEvent
from server.web.event_bus import WebEventBus


class EventCollector:
    def __init__(self):
        self.events = []

    def publish(self, event, payload, target_tab_id=''):
        self.events.append((event, payload, target_tab_id))


class TestTaskOutputBatching(unittest.TestCase):
    def make_runner(self):
        runner = object.__new__(WebTaskRunner)
        runner.event_bus = EventCollector()
        runner.task_store = SimpleNamespace(
            get_task=lambda task_id: {'status': 'success'},
            finish_task=lambda *args, **kwargs: None,
            delete_task=lambda task_id: None,
        )
        history = []
        runner.activity_coordinator = SimpleNamespace(
            append_output=lambda session, entry, status, text, eof: history.append((status, text)),
            finish=lambda *args, **kwargs: None,
        )
        runner.logger = SimpleNamespace(exception=lambda *args, **kwargs: None)
        context = SimpleNamespace(task_id='task-1', client_id='client-1', tab_id='tab-1',
            history_entry_id='history-1', metadata={'operation_id': 'op-1'},
            command='pyexec_stream test', command_id=123, task_type='command', session=SimpleNamespace(
                get_foreground_task=lambda: {}, session_info=SimpleNamespace(cwd='/tmp')))
        return runner, context, history

    def test_ten_thousand_chunks_collapse_without_loss_or_reordering(self):
        runner, context, history = self.make_runner()
        source = [f'RCH-{i:05d}' for i in range(1, 10001)]
        events = (CommandExecutionEvent.chunk(1, text) for text in source)
        runner._run_task_events(context, events)
        published = runner.event_bus.events
        assert published[-1][0] == 'command_complete'
        assert all(event in ('command_result', 'command_result_batch') for event, _, _ in published[:-1])
        assert len(published) < 200, len(published)
        values = []
        for event, payload, tab in published[:-1]:
            self.assertEqual(tab, 'tab-1')
            if event == 'command_result':
                values.append((payload['status'], payload['text']))
            else:
                values.extend((item['status'], item['text']) for item in payload['results'])
        self.assertEqual(values, [(1, text) for text in source])
        self.assertEqual(history, values)
        self.assertEqual(published[-1][1]['status'], 'success')

    def test_burst_does_not_overflow_actual_512_slot_tab_event_queue(self):
        async def scenario():
            bus = WebEventBus()
            queue = bus.subscribe_async(tab_id='tab-1', max_pending=512)
            other = bus.subscribe_async(tab_id='tab-2', max_pending=512)
            runner, context, _ = self.make_runner()
            runner.event_bus = bus
            events = (CommandExecutionEvent.chunk(1, f'RCH-{i}') for i in range(10000))
            runner._run_task_events(context, events)
            await asyncio.sleep(0.08)
            queued = []
            while not queue.empty():
                queued.append(queue.get_nowait())
            self.assertTrue(queued)
            self.assertNotIn(None, queued, 'queue overflow must not close the executing tab')
            self.assertEqual(queued[-1]['event'], 'command_complete')
            self.assertLess(len(queued), 200)
            self.assertTrue(other.empty(), 'other tabs do not receive command result events')
            bus.unsubscribe(queue)
            bus.unsubscribe(other)
        asyncio.run(scenario())

    def test_timer_flushes_sparse_results_before_command_finishes(self):
        batches = []
        batch = _TaskResultBatch(lambda result: batches.append(result))
        batch.add(1, 'first')
        time.sleep(0.09)
        self.assertEqual(batches, [[{'status': 1, 'text': 'first'}]])
        batch.add(0, 'error later')
        batch.close()
        self.assertEqual(batches[-1], [{'status': 0, 'text': 'error later'}])
        time.sleep(0.06)
        self.assertEqual(len(batches), 2, 'cancelled timer must not publish after completion')

    def test_batch_preserves_empty_chunks_unicode_and_mixed_status(self):
        runner, context, _ = self.make_runner()
        source = [(1, 'hello'), (1, ''), (0, '中文🙂'), (1, '\nembedded newline')]
        batch = _TaskResultBatch(lambda items: runner._publish_task_result_batch(context, items))
        for status, text in source:
            batch.add(status, text)
        batch.close()
        self.assertEqual(len(runner.event_bus.events), 1)
        event, payload, tab = runner.event_bus.events[0]
        self.assertEqual(event, 'command_result_batch')
        self.assertEqual([(r['status'], r['text']) for r in payload['results']], source)
        self.assertEqual(payload['metadata']['operation_id'], 'op-1')
        self.assertEqual(tab, 'tab-1')


if __name__ == '__main__':
    unittest.main()
