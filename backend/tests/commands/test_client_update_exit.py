import socket
from types import SimpleNamespace

from client.commands.common.mixins import update_ops
from client.commands.common.mixins.update_ops import CommandUpdateMixin


class _RawSocket:
    def __init__(self, events, fail_shutdown=False):
        self.events = events
        self.fail_shutdown = fail_shutdown

    def shutdown(self, how):
        self.events.append(("shutdown", how))
        if self.fail_shutdown:
            raise OSError("already closed")


class _Connection:
    def __init__(self, events, fail_shutdown=False):
        self.events = events
        self.socket = _RawSocket(events, fail_shutdown=fail_shutdown)

    def report_session_end(self, reason, *, command=""):
        self.events.append(("report", reason, command))

    def close(self):
        self.events.append(("close",))


def _host(events, *, drain=0.5, fail_shutdown=False):
    return SimpleNamespace(
        socket=_Connection(events, fail_shutdown=fail_shutdown),
        WINDOWS_UPDATE_SOCKET_DRAIN_SECONDS=drain,
    )


def test_windows_update_orders_session_end_before_send_shutdown_and_close(monkeypatch):
    events = []
    host = _host(events, drain=0.25)
    monkeypatch.setattr(update_ops.os, "name", "nt")
    monkeypatch.setattr(update_ops.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    CommandUpdateMixin._close_update_connection(host)

    assert events == [
        ("report", "client_update", "update"),
        ("shutdown", socket.SHUT_WR),
        ("sleep", 0.25),
        ("close",),
    ]


def test_non_windows_update_keeps_direct_close_path(monkeypatch):
    events = []
    host = _host(events)
    monkeypatch.setattr(update_ops.os, "name", "posix")
    monkeypatch.setattr(update_ops.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    CommandUpdateMixin._close_update_connection(host)

    assert events == [
        ("report", "client_update", "update"),
        ("close",),
    ]


def test_windows_update_still_closes_if_send_shutdown_is_already_unavailable(monkeypatch):
    events = []
    host = _host(events, fail_shutdown=True)
    monkeypatch.setattr(update_ops.os, "name", "nt")
    monkeypatch.setattr(update_ops.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    CommandUpdateMixin._close_update_connection(host)

    assert events == [
        ("report", "client_update", "update"),
        ("shutdown", socket.SHUT_WR),
        ("close",),
    ]
