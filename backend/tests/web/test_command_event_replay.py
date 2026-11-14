"""A short WebSocket disconnect must not swallow fast Server Builtin output."""
import asyncio
import threading

from server.web.event_bus import WebEventBus


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


def test_replay_is_bounded_and_does_not_replay_normal_notifications():
    async def scenario():
        bus = WebEventBus()
        bus.publish('command_result', {'text': 'x' * (1024 * 1024)}, target_tab_id='tab')
        bus.publish('notification_center_updated', {'action': 'added'}, target_tab_id='tab')
        q = bus.subscribe_async(tab_id='tab', replay_after=0,
                                replay_epoch=bus._replay_epoch, with_cursor=True)
        assert (await q.get())['event'] == 'stream_cursor'
        assert q.empty()
        bus.unsubscribe(q)
    asyncio.run(scenario())
