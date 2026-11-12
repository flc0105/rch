"""Run_web owns the shutdown sequence and only execs again for Restart."""

import asyncio
import threading
import unittest
from unittest.mock import patch

import run_web


class FakeConnection:
    def __init__(self, calls):
        self.calls = calls

    def close(self):
        self.calls.append('connection.close')


class FakeServer:
    def __init__(self, _address, calls):
        self.calls = calls
        self.connections = type('Connections', (), {
            'all': lambda self: [FakeConnection(calls)],
        })()
        self.listener_manager = type('Listeners', (), {
            'stop_all': lambda self: calls.append('listener.stop_all'),
        })()

    def serve(self):
        self.calls.append('tcp.start')

    def heartbeat_loop(self, stop_event):
        stop_event.wait(2)
        self.calls.append('heartbeat.stop')

    def schedule_startup_cleanup(self):
        self.calls.append('cleanup.scheduled')


class FakeHttpServer:
    def __init__(self, lifecycle, action, calls):
        self.lifecycle = lifecycle
        self.action = action
        self.calls = calls
        self.stopped = threading.Event()

    def serve_forever(self):
        self.calls.append('http.serve')
        self.lifecycle.reserve(self.action)
        self.lifecycle.activate()
        if not self.stopped.wait(2):
            raise AssertionError('HTTP shutdown was not coordinated')

    def shutdown(self):
        self.calls.append('http.shutdown')
        self.stopped.set()

    def server_close(self):
        self.calls.append('http.close')


class ServerEntrypointLifecycleTests(unittest.TestCase):
    def run_action(self, action):
        calls = []
        state = {}

        def make_app(server, lifecycle):
            state['lifecycle'] = lifecycle
            return lifecycle

        def make_http(*args, **kwargs):
            return FakeHttpServer(state['lifecycle'], action, calls)

        async def ws_runner(server, app, ready, stop_event):
            ready.set()
            await asyncio.to_thread(stop_event.wait)
            calls.append('ws.stop')

        with patch.object(run_web, 'Server', side_effect=lambda addr: FakeServer(addr, calls)), \
                patch.object(run_web, 'install_server_file_logging'), \
                patch.object(run_web, 'create_app', side_effect=make_app), \
                patch.object(run_web, 'make_server', side_effect=make_http), \
                patch.object(run_web, 'run_ws_server', side_effect=ws_runner), \
                patch.object(run_web.os, 'execv') as execv:
            run_web.main()

        self.assertIn('http.close', calls)
        self.assertIn('listener.stop_all', calls)
        self.assertIn('connection.close', calls)
        self.assertIn('ws.stop', calls)
        self.assertLess(calls.index('http.close'), calls.index('listener.stop_all'))
        self.assertLess(calls.index('listener.stop_all'), calls.index('ws.stop'))
        return calls, execv

    def test_shutdown_exits_without_exec(self):
        calls, execv = self.run_action('shutdown')
        self.assertIn('heartbeat.stop', calls)
        execv.assert_not_called()

    def test_restart_execs_own_entry_after_cleanup(self):
        _calls, execv = self.run_action('restart')
        execv.assert_called_once()
        args = execv.call_args.args
        self.assertEqual(args[0], run_web.sys.executable)
        self.assertEqual(args[1][0], run_web.sys.executable)
        self.assertTrue(args[1][1].endswith('/backend/run_web.py'))


if __name__ == '__main__':
    unittest.main()
