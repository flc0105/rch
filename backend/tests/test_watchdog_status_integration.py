"""Watchdog status keeps three monitoring modes separate with one-level fields."""
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from client.commands.common.mixins.watchdog_ops import CommandWatchdogMixin
from client.watchdog.client_guard_manager import ClientGuardManager
from client.watchdog.process_watchdog import _POLL_INTERVAL, get_process_watchdog_status_payload
from core.utils.command_output import StructuredCommandResult, render_structured_result
from client.commands.runtime.shell_command_runner import ShellCommandRunner


class WatchdogStatusIntegrationTests(unittest.TestCase):
    def test_process_status_disabled_does_not_claim_running(self):
        with patch('client.config.runtime_config.PROCESS_WATCHDOG_ENABLED', False), \
             patch('client.watchdog.process_watchdog._alive') as is_alive:
            status = get_process_watchdog_status_payload()
        self.assertFalse(status['enabled'])
        self.assertFalse(status['supervisor_alive'])
        self.assertIsNone(status['supervisor_pid'])
        self.assertEqual(status['poll_interval_seconds'], _POLL_INTERVAL)
        self.assertTrue(status['log_path'].endswith(os.path.join('rchclient', 'logs', 'process_watchdog.log')))
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
        with patch('client.config.runtime_config.PROCESS_WATCHDOG_ENABLED', False):
            status, text_output = runner.execute(request, 'watchdog')
            json_status, json_output = runner.execute(request, 'watchdog --json')
        self.assertEqual((status, json_status), (1, 1))
        self.assertTrue(text_output.startswith('[client]\nid = example-client\npid = '))
        self.assertEqual(text_output.count('\n\n['), 3)
        self.assertNotIn("{'", text_output)
        payload = json.loads(json_output)
        self.assertEqual(list(payload), ['client', 'remote_watchdog', 'local_watchdog', 'process_watchdog'])
        self.assertEqual(payload['client']['id'], 'example-client')
        self.assertEqual(payload['remote_watchdog']['enabled'], False)

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


if __name__ == '__main__':
    unittest.main()
