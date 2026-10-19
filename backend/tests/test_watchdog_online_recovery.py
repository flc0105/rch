"""Watchdog recovery provenance appears only on the first online event."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from client.watchdog.recovery_source import (
    RECOVERY_SOURCE_ENV, consume_recovery_source,
)
from client.watchdog.remote_watchdog import WatchdogActionExecutor
from client.watchdog.watchdog_process import ClientWatchdogWorker
from client.watchdog.process_watchdog import without_process_watchdog_environment
from client.bootstrap.connection_lifecycle import ClientConnectionLifecycle
from server.application.connection.connection_service import WebConnectionService
from server.application.preferences.notification_event_projector import NotificationEventProjector


class RecoverySourceTests(unittest.TestCase):
    def test_startup_consumes_valid_source_once_and_rejects_unknown(self):
        for source in ('local_watchdog', 'process_watchdog'):
            with self.subTest(source=source), patch.dict(os.environ, {RECOVERY_SOURCE_ENV: source}):
                self.assertEqual(consume_recovery_source(), source)
                self.assertNotIn(RECOVERY_SOURCE_ENV, os.environ)
                self.assertEqual(consume_recovery_source(), '')
        with patch.dict(os.environ, {RECOVERY_SOURCE_ENV: 'unknown'}):
            self.assertEqual(consume_recovery_source(), '')

    def test_new_supervision_chain_scrubs_recovery_source(self):
        values = {'PATH': '/bin', RECOVERY_SOURCE_ENV: 'local_watchdog',
                  'RCH_PROCESS_WATCHDOG_PID': '100'}
        self.assertEqual(without_process_watchdog_environment(values), {'PATH': '/bin'})

    def test_local_watchdog_marks_spawn_but_remote_does_not(self):
        with patch('client.watchdog.remote_watchdog.subprocess.Popen') as popen, \
             patch('client.watchdog.remote_watchdog.without_process_watchdog_environment', side_effect=lambda: {}):
            executor = WatchdogActionExecutor(2, '/tmp', ['python', 'client.py'])
            executor.spawn_restarted_parent(recovery_source='local_watchdog')
            self.assertEqual(popen.call_args.kwargs['env'][RECOVERY_SOURCE_ENV], 'local_watchdog')
            executor.spawn_restarted_parent()
            self.assertNotIn(RECOVERY_SOURCE_ENV, popen.call_args.kwargs['env'])

        with patch('client.watchdog.watchdog_process._build_unused', create=True):
            worker = ClientWatchdogWorker(
                parent_pid=2, client_id='abc', launch_cwd='/tmp',
                parent_launch_argv=['python', 'client.py'],
                remote_http_watchdog_enabled=False,
                remote_http_watchdog_base_url='',
                remote_http_watchdog_interval_seconds=15,
                remote_watchdog_log_file_path='/tmp/remote.log',
                local_watchdog_enabled=True,
                local_watchdog_timeout_seconds=10,
                local_watchdog_heartbeat_file_path='/tmp/heartbeat',
                local_watchdog_log_file_path='/tmp/local.log',
            )
            with patch.object(worker._action_executor, 'restart_parent_and_exit') as restart:
                worker._local_monitor.action_executor.restart_parent()
                restart.assert_called_once_with(recovery_source='local_watchdog')

    def test_process_supervisor_marks_restarted_child(self):
        from client.watchdog import process_watchdog
        captured = []

        def stop_after_launch(argv, **kwargs):
            captured.append(kwargs['env'])
            raise RuntimeError('stop test after launch')

        with patch.object(process_watchdog, '_logger', return_value=Mock()), \
             patch.object(process_watchdog, '_process_identity', return_value=1.0), \
             patch.object(process_watchdog, '_atomic_json'), \
             patch.object(process_watchdog, '_alive', return_value=False), \
             patch.object(process_watchdog, '_RETRY_DELAYS', (0,)), \
             patch.object(process_watchdog.subprocess, 'Popen', side_effect=stop_after_launch), \
             patch.object(process_watchdog.shutil, 'rmtree'):
            with self.assertRaisesRegex(RuntimeError, 'stop test after launch'):
                process_watchdog.run_process_supervisor('/tmp/test-watchdog-session', 987654, 1.0,
                                                         ['python', 'client.py'], '/tmp')
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][RECOVERY_SOURCE_ENV], 'process_watchdog')

    def test_handshake_consumes_source_only_after_send(self):
        client = SimpleNamespace(client_id='c1', recovery_source='process_watchdog',
                                 server=Mock(), info=None)
        lifecycle = ClientConnectionLifecycle(client)
        with patch('client.bootstrap.connection_lifecycle.ClientInfoBuilder') as builder:
            builder.return_value.build.side_effect = lambda: {'type': 'info', 'id': 'c1'}
            client.server.send.side_effect = OSError('offline')
            with self.assertRaises(OSError):
                lifecycle.handshake()
            self.assertEqual(client.recovery_source, 'process_watchdog')
            client.server.send.side_effect = None
            lifecycle.handshake()
            self.assertEqual(client.server.send.call_args.args[0]['recovery_source'], 'process_watchdog')
            self.assertEqual(client.recovery_source, '')
            lifecycle.handshake()
            self.assertNotIn('recovery_source', client.server.send.call_args.args[0])

    def test_server_only_emits_allowlisted_source_on_online(self):
        session = Mock()
        published = []
        service = Mock()
        service.serialize_connection.return_value = {'client_id': 'c1', 'hostname': 'host'}
        service._decorate_connection_with_device_view_prefs.side_effect = lambda payload, **kwargs: payload
        service.event_bus.publish.side_effect = lambda event, payload: published.append((event, payload))
        with patch('server.application.connection.connection_service.build_client_revision_manifest', return_value={}):
            for source in ('local_watchdog', 'process_watchdog', 'garbage', ''):
                session.get_info_extra.return_value = source
                WebConnectionService.publish_connection_online(service, session)
                name, payload = published[-1]
                self.assertEqual(name, 'connection_online')
                self.assertEqual(payload.get('recovery_source', ''), source if source in ('local_watchdog', 'process_watchdog') else '')

    def test_notification_history_matches_recovery_source(self):
        projector = NotificationEventProjector(history_store=Mock(), server=Mock())
        for source, suffix in [('', ''), ('local_watchdog', ' (recovered by Local Watchdog)'),
                               ('process_watchdog', ' (recovered by Process Watchdog)'),
                               ('invalid', '')]:
            with self.subTest(source=source):
                notification = projector._build_connection_online({
                    'connection': {'client_id': 'c1', 'hostname': 'Mac'},
                    'recovery_source': source,
                })
                self.assertEqual(notification['title'], 'Device Online')
                self.assertEqual(notification['message'], 'Mac is now available' + suffix)
                self.assertEqual(notification['context'].get('recovery_source', ''), source if suffix else '')


if __name__ == '__main__':
    unittest.main()
