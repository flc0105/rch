from types import SimpleNamespace

import pytest

from client.commands.common.mixins import update_ops
from client.commands.common.mixins.update_ops import CommandUpdateMixin


class _Connection:
    def __init__(self, events):
        self.events = events

    def report_session_end(self, reason, *, command=''):
        self.events.append(('report', reason, command))
        return True

    def close(self):
        self.events.append(('close',))


@pytest.mark.parametrize('platform', ['nt', 'posix'])
def test_update_close_waits_for_protocol_reporting_before_closing(monkeypatch, platform):
    events = []
    host = SimpleNamespace(socket=_Connection(events))
    monkeypatch.setattr(update_ops.os, 'name', platform)

    CommandUpdateMixin._close_update_connection(host)

    assert events == [
        ('report', 'client_update', 'update'),
        ('close',),
    ]


def test_update_closes_even_when_session_end_ack_times_out():
    events = []
    host = SimpleNamespace(socket=_Connection(events))
    host.socket.report_session_end = lambda reason, *, command: events.append(('report', reason, command)) or False

    CommandUpdateMixin._close_update_connection(host)

    assert events == [('report', 'client_update', 'update'), ('close',)]
