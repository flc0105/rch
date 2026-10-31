"""EventBus WebSocket subscribers run without idle per-connection worker threads."""
import asyncio
import threading

from server.web.event_bus import WebEventBus


def test_async_subscribers_no_worker_threads_and_tab_isolation():
    async def scenario():
        bus = WebEventBus()
        initial_threads = threading.active_count()
        subscribers = [bus.subscribe_async(tab_id=f'tab-{i}') for i in range(80)]
        assert threading.active_count() == initial_threads
        producer = threading.Thread(target=lambda: bus.publish('command_complete', {'task_id': 't'}, target_tab_id='tab-47'))
        producer.start()
        producer.join()
        received = await asyncio.wait_for(subscribers[47].get(), 2)
        assert received['event'] == 'command_complete'
        assert received['data']['task_id'] == 't'
        assert all(q.empty() for i, q in enumerate(subscribers) if i != 47)
        for q in subscribers:
            bus.unsubscribe(q)
        assert not bus._subscribers
    asyncio.run(scenario())


def test_async_slow_consumer_is_closed_once():
    async def scenario():
        bus = WebEventBus()
        q = bus.subscribe_async(max_pending=2)
        for n in range(5):
            bus.publish('device_event', {'n': n})
        await asyncio.sleep(0.02)
        assert await asyncio.wait_for(q.get(), 1) is None
        assert q.empty()
        bus.unsubscribe(q)
    asyncio.run(scenario())
