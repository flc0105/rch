import unittest

from rch_notifier.sse import NotificationSseClient, parse_sse_lines


class SseParserTests(unittest.TestCase):
    def test_notification_event(self):
        events = list(parse_sse_lines([
            'id: abc',
            'event: notification',
            'data: {"title":"Hello"}',
            '',
        ]))
        self.assertEqual(1, len(events))
        self.assertEqual('abc', events[0].event_id)
        self.assertEqual('notification', events[0].event)
        self.assertEqual('Hello', events[0].json()['title'])

    def test_multiline_data_and_ping(self):
        events = list(parse_sse_lines([
            ': comment',
            'event: ping',
            'data: {"a":1,',
            'data: "b":2}',
            '',
        ]))
        self.assertEqual('ping', events[0].event)
        self.assertEqual({'a': 1, 'b': 2}, events[0].json())


class _FakeResponse:
    status_code = 200
    headers = {'Content-Type': 'text/event-stream; charset=utf-8'}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self, **_kwargs):
        return iter(['id: next', 'event: notification', 'data: {"id":"next"}', ''])


class _FakeSession:
    def __init__(self):
        self.last_headers = None

    def get(self, _url, *, headers, **_kwargs):
        self.last_headers = dict(headers)
        return _FakeResponse()


class NotificationSseClientTests(unittest.TestCase):
    def test_last_event_id_and_bearer_token_are_sent(self):
        session = _FakeSession()
        client = NotificationSseClient(url='http://server/api/notifications/stream', token='secret', session=session)
        events = list(client.events('cursor-1'))
        self.assertEqual('Bearer secret', session.last_headers['Authorization'])
        self.assertEqual('cursor-1', session.last_headers['Last-Event-ID'])
        self.assertEqual('next', events[0].event_id)


if __name__ == '__main__':
    unittest.main()
