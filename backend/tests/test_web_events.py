"""Ordered terminal events, tab isolation and reconnect replay."""

import asyncio
import threading
import unittest
from types import SimpleNamespace

from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.tasks.task_runner import WebTaskRunner
from server.web.event_bus import WebEventBus
from server.web.ws_origin import websocket_origin_allowed


def test_reconnect_replays_only_missed_tab_output_in_order():
    async def scenario():
        bus = WebEventBus()
        tab = 'current-browser-tab'
        initial = bus.subscribe_async(tab_id=tab, with_cursor=True)
        cursor = await initial.get()
        assert cursor['event'] == 'stream_cursor' and cursor['cursor'] == 0
        epoch = cursor['epoch']
        bus.publish('command_result', {'task_id': 'one', 'text': 'first'}, target_tab_id=tab)
        seen = await initial.get()
        assert seen['cursor'] == 1
        bus.unsubscribe(initial)

        # A fast job list completes while the browser's WS is reconnecting.
        producer = threading.Thread(target=lambda: (
            bus.publish('command_result', {'task_id': 'two', 'text': 'job list rows'}, target_tab_id=tab),
            bus.publish('command_complete', {'task_id': 'two', 'success': True}, target_tab_id=tab),
            bus.publish('command_result', {'task_id': 'other-tab', 'text': 'secret'}, target_tab_id='other-tab'),
        ))
        producer.start()
        producer.join()

        recovered = bus.subscribe_async(tab_id=tab, replay_after=seen['cursor'],
                                        replay_epoch=epoch, with_cursor=True)
        events = [await asyncio.wait_for(recovered.get(), 1) for _ in range(3)]
        assert [event['event'] for event in events] == [
            'command_result', 'command_complete', 'stream_cursor']
        assert [event['data']['task_id'] for event in events[:2]] == ['two', 'two']
        assert [event['cursor'] for event in events] == [2, 3, 4]
        assert recovered.empty(), 'already received output and other tab must not replay'
        bus.unsubscribe(recovered)

        # A different tab cannot request our private command-event history.
        stranger = bus.subscribe_async(tab_id='other-tab', replay_after=1,
                                       replay_epoch=epoch, with_cursor=True)
        other = await stranger.get()
        assert other['data']['task_id'] == 'other-tab'
        assert (await stranger.get())['event'] == 'stream_cursor'
        assert stranger.empty()
        bus.unsubscribe(stranger)

    asyncio.run(scenario())


def test_reconnect_after_server_restart_cannot_replay_old_epoch():
    async def scenario():
        bus = WebEventBus()
        bus.publish('command_complete', {'task_id': 'completed'}, target_tab_id='tab')
        q = bus.subscribe_async(tab_id='tab', replay_after=0,
                                replay_epoch='old-server-epoch', with_cursor=True)
        item = await q.get()
        assert item['event'] == 'stream_cursor' and item['cursor'] == 1
        assert item['epoch'] != 'old-server-epoch'
        assert q.empty()
        bus.unsubscribe(q)
    asyncio.run(scenario())


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
            append_client_result=lambda session, entry, result: history.append(result),
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
        self.assertEqual(history, [])
        self.assertEqual(published[-1][1]['status'], 'success')


def test_other_origins_and_ports_are_rejected():
    assert not websocket_origin_allowed('http://evil.test:15173', 'example.test:15173', 8085)
    assert not websocket_origin_allowed('http://example.test:15173', 'example.test:8086', 8085)
    assert not websocket_origin_allowed('file:///etc/passwd', 'example.test:15173', 8085)
    assert not websocket_origin_allowed('http://example.test:bad', 'example.test:15173', 8085)


def test_concurrent_tab_output_and_global_foreground_events_are_independent():
    async def scenario():
        bus = WebEventBus()
        a = bus.subscribe_async(tab_id='a', with_cursor=True)
        b = bus.subscribe_async(tab_id='b', with_cursor=True)
        await a.get(); await b.get()
        bus.publish('command_result', {'task_id': 'stream', 'text': 'probe 1'}, target_tab_id='a')
        bus.publish('command_result', {'task_id': 'config', 'text': 'config JSON'}, target_tab_id='b')
        bus.publish('command_complete', {'task_id': 'config'}, target_tab_id='b')
        bus.publish('foreground_task_changed', {'client_id': 'client', 'task': {'state': 'Running'}})
        bus.publish('command_result', {'task_id': 'stream', 'text': 'probe 2'}, target_tab_id='a')
        for event in ('command_result', 'command_result_batch', 'command_complete'):
            bus.publish(event, {'task_id': 'untargeted'})
        await asyncio.sleep(0)
        assert [(x['event'], x['data'].get('task_id')) for x in [a.get_nowait() for _ in range(3)]] == [
            ('command_result', 'stream'), ('foreground_task_changed', None), ('command_result', 'stream')]
        assert [(x['event'], x['data'].get('task_id')) for x in [b.get_nowait() for _ in range(3)]] == [
            ('command_result', 'config'), ('command_complete', 'config'), ('foreground_task_changed', None)]
        assert a.empty() and b.empty()
    asyncio.run(scenario())
