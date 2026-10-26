"""Focused behavior tests for project module: watchdog."""

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
import json
from client.commands.common.mixins.watchdog_ops import CommandWatchdogMixin
from client.watchdog.client_guard_manager import ClientGuardManager
from client.watchdog.process_watchdog import (
    _POLL_INTERVAL, ProcessWatchdogManager, get_process_watchdog_status_payload,
)
from core.utils.command_output import StructuredCommandResult, render_structured_result
from client.commands.runtime.shell_command_runner import ShellCommandRunner
from client.runtime.launch_context import LAUNCH_MODE_ENV, LAUNCH_SOURCE_ENV, is_launchd_managed_client


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


class LaunchdWatchdogPolicyTests(unittest.TestCase):
    def test_explicit_launchagent_and_launchdaemon_are_launchd_managed(self):
        for mode, source in (('user_service', 'launchagent'), ('system_service', 'launchdaemon')):
            with self.subTest(source=source), patch.dict(
                os.environ,
                {LAUNCH_MODE_ENV: mode, LAUNCH_SOURCE_ENV: source},
                clear=False,
            ):
                self.assertTrue(is_launchd_managed_client())

        with patch.dict(
            os.environ,
            {LAUNCH_MODE_ENV: 'user_service', LAUNCH_SOURCE_ENV: 'systemd_user'},
            clear=False,
        ):
            self.assertFalse(is_launchd_managed_client())

    def test_guard_manager_suppresses_remote_and_local_even_when_configured(self):
        guard = ClientGuardManager('launchd-client')
        with patch('client.watchdog.client_guard_manager.is_launchd_managed_client', return_value=True), \
             patch('client.watchdog.client_guard_manager.REMOTE_HTTP_WATCHDOG_ENABLED', True), \
             patch('client.watchdog.client_guard_manager.LOCAL_WATCHDOG_ENABLED', True):
            guard.start()
            self.assertIsNone(guard._watchdog_process)
            self.assertIsNone(guard._local_watchdog_feeder)
            status = guard.get_watchdog_status_payload()

        self.assertTrue(status['client']['watchdogs_suppressed'])
        self.assertEqual(status['client']['lifecycle_manager'], 'launchd')
        for key in ('remote_watchdog', 'local_watchdog'):
            self.assertTrue(status[key]['configured_enabled'])
            self.assertFalse(status[key]['enabled'])
            self.assertTrue(status[key]['suppressed'])
            self.assertEqual(status[key]['suppression_reason'], 'launchd')
        self.assertFalse(status['remote_watchdog']['worker_alive'])
        self.assertFalse(status['local_watchdog']['feeder_alive'])

    def test_process_manager_cannot_start_under_launchd(self):
        manager = ProcessWatchdogManager()
        with patch('client.watchdog.process_watchdog.is_launchd_managed_client', return_value=True), \
             patch('client.watchdog.process_watchdog.subprocess.Popen') as popen:
            manager.start()
        popen.assert_not_called()
        self.assertEqual(manager.session, '')
        self.assertIsNone(manager.supervisor_pid)

    def test_process_status_reports_configured_but_effectively_suppressed(self):
        manager = SimpleNamespace(supervisor_pid=4512, supervisor_started=123.5)
        with patch('client.config.runtime_config.PROCESS_WATCHDOG_ENABLED', True), \
             patch('client.watchdog.process_watchdog.is_launchd_managed_client', return_value=True), \
             patch('client.watchdog.process_watchdog._alive') as is_alive:
            status = get_process_watchdog_status_payload(manager)
        self.assertTrue(status['configured_enabled'])
        self.assertFalse(status['enabled'])
        self.assertTrue(status['suppressed'])
        self.assertEqual(status['suppression_reason'], 'launchd')
        self.assertIsNone(status['supervisor_pid'])
        self.assertFalse(status['supervisor_alive'])
        is_alive.assert_not_called()


class WatchdogStatusIntegrationTests(unittest.TestCase):
    def test_process_status_disabled_does_not_claim_running(self):
        with patch('client.config.runtime_config.PROCESS_WATCHDOG_ENABLED', False), \
             patch('client.watchdog.process_watchdog._alive') as is_alive:
            status = get_process_watchdog_status_payload()
        self.assertFalse(status['enabled'])
        self.assertFalse(status['supervisor_alive'])
        self.assertIsNone(status['supervisor_pid'])
        self.assertEqual(status['poll_interval_seconds'], _POLL_INTERVAL)
        self.assertRegex(status['log_path'], r'rch_client_temp(?:_u\d+)?[/\\]watchdog_logs[/\\]process_watchdog\.log$')
        is_alive.assert_not_called()

    def test_supervisor_identity_probed_independently(self):
        manager = SimpleNamespace(supervisor_pid=4512, supervisor_started=123.5)
        with patch('client.config.runtime_config.PROCESS_WATCHDOG_ENABLED', True), \
             patch('client.watchdog.process_watchdog._alive', return_value=True) as is_alive:
            status = get_process_watchdog_status_payload(manager)
        self.assertEqual((status['supervisor_pid'], status['supervisor_alive']), (4512, True))
        is_alive.assert_called_once_with(4512, 123.5)

    def test_remote_and_local_share_the_same_worker_identity(self):
        guard = ClientGuardManager('example-client')
        guard._watchdog_process = SimpleNamespace(get_pid=lambda: 20, is_alive=lambda: True)
        guard._local_watchdog_feeder = SimpleNamespace(is_alive=lambda: True, get_thread_name=lambda: 'Heartbeats')
        status = guard.get_watchdog_status_payload()
        self.assertEqual(set(status), {'client', 'remote_watchdog', 'local_watchdog'})
        self.assertEqual(status['client']['id'], 'example-client')
        self.assertEqual(status['client']['pid'], os.getpid())
        remote = status['remote_watchdog']
        local = status['local_watchdog']
        self.assertEqual(remote['worker_pid'], local['worker_pid'])
        self.assertEqual(remote['worker_pid'], 20)
        self.assertEqual(remote['worker_alive'], local['worker_alive'])
        self.assertEqual(remote['control_url'].split('/')[-1], 'control')
        self.assertIn('interval_seconds', remote)
        self.assertIn('heartbeat_interval_seconds', local)
        self.assertIn('timeout_seconds', local)
        self.assertEqual(local['feeder_thread_name'], 'Heartbeats')
        self.assertTrue(local['feeder_alive'])
        for section in status.values():
            self.assertTrue(all(not isinstance(v, dict) for v in section.values()))

    def test_watchdog_command_uses_only_nested_sections_in_json_and_text(self):
        owner = CommandWatchdogMixin()
        guard = ClientGuardManager('example-client')
        guard._watchdog_process = SimpleNamespace(get_pid=lambda: 20, is_alive=lambda: True)
        manager = SimpleNamespace(supervisor_pid=4512, supervisor_started=123.5)
        owner.socket = SimpleNamespace(guard_manager=guard, process_watchdog_manager=manager)
        with patch('client.config.runtime_config.PROCESS_WATCHDOG_ENABLED', True), \
             patch('client.watchdog.process_watchdog._alive', return_value=True):
            result = owner.watchdog('--json')
        self.assertEqual(result.status, 1)
        self.assertEqual(set(result.data), {'client', 'remote_watchdog', 'local_watchdog', 'process_watchdog'})
        self.assertEqual(result.data['process_watchdog']['supervisor_pid'], 4512)
        self.assertEqual(result.data['remote_watchdog']['worker_pid'], 20)
        self.assertEqual(result.data['local_watchdog']['worker_pid'], 20)
        for section in result.data.values():
            self.assertTrue(all(not isinstance(v, dict) for v in section.values()))
        status, json_output = render_structured_result(result, 'json')
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(json_output), result.data)
        status, text_output = render_structured_result(result, 'text')
        self.assertEqual(status, 1)
        self.assertEqual(result.shape, 'grouped_dict')
        self.assertEqual(
            [line for line in text_output.splitlines() if line.startswith('[')],
            ['[client]', '[remote_watchdog]', '[local_watchdog]', '[process_watchdog]'],
        )
        self.assertIn('[client]\nid = example-client\npid = ', text_output)
        self.assertIn('[remote_watchdog]\nenabled = ', text_output)
        self.assertIn('worker_pid = 20', text_output)
        self.assertIn('supervisor_pid = 4512', text_output)
        self.assertIn('poll_interval_seconds = 0.5', text_output)
        self.assertIn('\n\n[local_watchdog]\n', text_output)
        self.assertNotIn("{'enabled':", text_output)
        self.assertNotIn("{'id':", text_output)
        runner = ShellCommandRunner(executor=None)
        self.assertEqual(runner._render_command_result(result), (1, text_output))
        self.assertEqual(json.loads(runner._render_command_result(result, 'json')[1]), result.data)
        self.assertNotIn('remote_enabled', json_output)
        self.assertNotIn('watchdog_pid', json_output)
        self.assertNotIn('process_alive', json_output)

    def test_watchdog_shell_pipeline_renders_text_and_json_separately(self):
        owner = CommandWatchdogMixin()
        owner.socket = SimpleNamespace(guard_manager=ClientGuardManager('example-client'))

        class Executor:
            command_variable_resolver = SimpleNamespace(resolve=lambda raw, command_id=None: raw)

            def execute_bound_request(self, request, callback):
                return callback(owner)

        runner = ShellCommandRunner(Executor())
        request = SimpleNamespace(command_id='test')
        # Do not depend on an actual user's runtime_config.json watchdog overrides.
        for remote_enabled in (False, True):
            with self.subTest(remote_enabled=remote_enabled), \
                 patch('client.config.runtime_config.PROCESS_WATCHDOG_ENABLED', False), \
                 patch('client.watchdog.client_guard_manager.REMOTE_HTTP_WATCHDOG_ENABLED', remote_enabled):
                status, text_output = runner.execute(request, 'watchdog')
                json_status, json_output = runner.execute(request, 'watchdog --json')

                self.assertEqual((status, json_status), (1, 1))
                self.assertTrue(text_output.startswith('[client]\nid = example-client\npid = '))
                self.assertEqual(text_output.count('\n\n['), 3)
                self.assertNotIn("{'", text_output)
                payload = json.loads(json_output)
                self.assertEqual(list(payload), ['client', 'remote_watchdog', 'local_watchdog', 'process_watchdog'])
                self.assertEqual(payload['client']['id'], 'example-client')
                self.assertIs(payload['remote_watchdog']['enabled'], remote_enabled)
                self.assertIn(f'enabled = {remote_enabled}', text_output.split('[remote_watchdog]\n', 1)[1].split('\n\n', 1)[0])

    def test_grouped_format_does_not_change_other_dict_commands(self):
        result = StructuredCommandResult(status=1, data={'mode': 'normal'}, shape='dict', width=12)
        self.assertEqual(render_structured_result(result, 'text'), (1, 'mode        normal'))
        grouped = StructuredCommandResult(
            status=1,
            data={'group': {'enabled': False, 'timeout_seconds': 1.5}},
            shape='grouped_dict',
        )
        self.assertEqual(
            render_structured_result(grouped, 'text'),
            (1, '[group]\nenabled = False\ntimeout_seconds = 1.5'),
        )
        with self.assertRaises(ValueError):
            render_structured_result(
                StructuredCommandResult(status=1, data={'group': {'nested': {'third': 1}}}, shape='grouped_dict'),
                'text',
            )

    def test_missing_process_manager_does_not_hide_status(self):
        owner = CommandWatchdogMixin()
        guard = ClientGuardManager('example-client')
        owner.socket = SimpleNamespace(guard_manager=guard)
        with patch('client.config.runtime_config.PROCESS_WATCHDOG_ENABLED', True):
            result = owner.watchdog()
        self.assertTrue(result.data['process_watchdog']['enabled'])
        self.assertIsNone(result.data['process_watchdog']['supervisor_pid'])
        self.assertFalse(result.data['process_watchdog']['supervisor_alive'])
        self.assertFalse(result.data['remote_watchdog']['worker_alive'])
