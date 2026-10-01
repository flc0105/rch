import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.application.command.command_notify_builtin_support import CommandNotifyBuiltinSupport
from server.application.command.command_planner import CommandPlanner
from server.application.command.command_types import COMMAND_TYPE_ACMD, COMMAND_TYPE_COMMAND
from server.application.device_events.device_event_service import DeviceEventService
from server.application.preferences.notification_event_projector import NotificationEventProjector
from server.application.web.device_event_api import WebDeviceEventApi
from server.web.event_bus import WebEventBus


class _AliasManager:
    def __init__(self, aliases=None):
        self.aliases = dict(aliases or {})

    def resolve_alias(self, name, arg, conn=None):
        del conn
        if name not in self.aliases:
            raise KeyError(name)
        command = self.aliases[name]
        if arg:
            command = f'{command} {arg}'
        return {
            'alias': name,
            'platform': 'common',
            'command': command,
        }


class CommandNotifyBuiltinSupportTests(unittest.TestCase):
    def setUp(self):
        self.ingest = Mock(return_value={'event_id': 'event-1'})
        self.server = SimpleNamespace(
            web_service=SimpleNamespace(
                device_event_api=SimpleNamespace(ingest=self.ingest),
            ),
        )
        self.conn = SimpleNamespace(
            session_info=SimpleNamespace(
                client_id='client-1',
                hostname='host-1',
            ),
        )
        self.plans = []
        self.plan_results = {}

        def plan_executor(plan):
            self.plans.append(plan)

            def runner():
                for item in self.plan_results.get(plan.get('command'), [(1, 'ok')]):
                    yield item

            return runner

        self.planner = CommandPlanner(
            alias_manager=_AliasManager({'gi': 'getinfo'}),
            plan_executor=plan_executor,
            error_executor=lambda error: iter([(0, str(error))]),
            conn=self.conn,
        )
        self.support = CommandNotifyBuiltinSupport(
            server=self.server,
            conn=self.conn,
            plan_builder=self.planner,
            history_entry_id_provider=lambda: 'history-1',
        )

    def _assert_success_event(self):
        payload = self.ingest.call_args.args[0]
        self.assertEqual('command.notify.finished', payload['kind'])
        self.assertEqual('client-1', payload['client_id'])
        self.assertEqual('host-1', payload['hostname'])
        self.assertEqual('server_builtin', payload['source']['type'])
        self.assertEqual('notify', payload['source']['name'])
        self.assertEqual('history-1', payload['source']['id'])
        self.assertEqual('success', payload['data']['status'])
        self.assertGreaterEqual(payload['data']['duration_ms'], 0)
        self.assertNotIn('command', payload['data'])

    def test_notify_is_exposed_as_server_builtin_candidate(self):
        candidate = next(
            item for item in BuiltinCommandHandler.WEB_COMMAND_TEMPLATES
            if item.get('name') == 'notify'
        )
        self.assertEqual('notify ', candidate['template'])
        self.assertIn('notify <client-command>', candidate['help'])

    def test_notify_preserves_default_client_commands(self):
        for command in ('shell echo hello', 'read python -V', 'getinfo'):
            with self.subTest(command=command):
                self.plans.clear()
                self.ingest.reset_mock()
                output = list(self.support.notify(command))

                self.assertEqual([(1, 'ok')], output)
                self.assertEqual(1, len(self.plans))
                self.assertEqual(command, self.plans[0]['command'])
                self.assertEqual(COMMAND_TYPE_COMMAND, self.plans[0]['command_type'])
                self._assert_success_event()

    def test_notify_preserves_acmd_planning(self):
        command = 'acmd ps --name python --limit 5'
        output = list(self.support.notify(command))

        self.assertEqual([(1, 'ok')], output)
        self.assertEqual(1, len(self.plans))
        plan = self.plans[0]
        self.assertEqual(COMMAND_TYPE_ACMD, plan['command_type'])
        self.assertEqual('ps', plan['extra']['name'])
        self.assertEqual({'name': 'python', 'limit': '5'}, plan['extra']['args'])
        self._assert_success_event()

    def test_notify_preserves_alias_resolution(self):
        output = list(self.support.notify('gi'))

        self.assertEqual([(1, 'ok')], output)
        self.assertEqual('getinfo', self.plans[0]['command'])
        self.assertEqual(COMMAND_TYPE_COMMAND, self.plans[0]['command_type'])
        self._assert_success_event()

    def test_notify_marks_failed_when_inner_stream_contains_error(self):
        self.plan_results['shell false'] = [
            (1, 'starting'),
            (0, 'Command exited with code 1'),
        ]

        output = list(self.support.notify('shell false'))

        self.assertEqual(self.plan_results['shell false'], output)
        payload = self.ingest.call_args.args[0]
        self.assertEqual('failed', payload['data']['status'])
        self.assertTrue(payload['message'].startswith('Failed · '))

    def test_notify_usage_does_not_emit_event(self):
        self.assertEqual([(0, 'Usage: notify <client-command>')], list(self.support.notify('')))
        self.ingest.assert_not_called()

    def test_notify_event_failure_does_not_change_command_output(self):
        self.ingest.side_effect = RuntimeError('notification unavailable')

        with patch('server.application.command.command_notify_builtin_support.logger.error'):
            output = list(self.support.notify('getinfo'))

        self.assertEqual([(1, 'ok')], output)


class _MemoryNotificationHistory:
    def __init__(self):
        self.notifications = []

    def add_notification(self, notification):
        stored = dict(notification)
        stored['id'] = f'n-{len(self.notifications) + 1}'
        self.notifications.append(stored)
        return stored, True


class CommandNotifyEventPipelineTests(unittest.TestCase):
    def test_notify_flows_through_existing_device_event_and_notification_bus(self):
        session = SimpleNamespace(
            session_info=SimpleNamespace(
                client_id='client-1',
                hostname='host-1',
            ),
        )
        bus = WebEventBus()
        history = _MemoryNotificationHistory()
        server = SimpleNamespace()
        server.get_target_connection_by_client_id = lambda client_id: session if client_id == 'client-1' else None
        projector = NotificationEventProjector(history_store=history, server=server)
        bus.set_notification_recorder(projector.record_event)
        device_event_api = WebDeviceEventApi(DeviceEventService(server=server, event_bus=bus))
        server.web_service = SimpleNamespace(device_event_api=device_event_api)

        raw_events = bus.subscribe(event_types={'device_event'})
        notification_updates = bus.subscribe(event_types={'notification_center_updated'})

        plans = []

        def plan_executor(plan):
            plans.append(plan)
            return lambda: iter([(1, 'done')])

        planner = CommandPlanner(
            alias_manager=_AliasManager(),
            plan_executor=plan_executor,
            error_executor=lambda error: iter([(0, str(error))]),
            conn=session,
        )
        support = CommandNotifyBuiltinSupport(
            server=server,
            conn=session,
            plan_builder=planner,
            history_entry_id_provider=lambda: 'history-1',
        )

        self.assertEqual([(1, 'done')], list(support.notify('getinfo')))

        raw_item = raw_events.get_nowait()
        self.assertEqual('device_event', raw_item['event'])
        self.assertEqual('command.notify.finished', raw_item['data']['kind'])
        self.assertEqual('success', raw_item['data']['data']['status'])

        notification_item = notification_updates.get_nowait()
        self.assertEqual('notification_center_updated', notification_item['event'])
        notification = notification_item['data']['notification']
        self.assertEqual('device_event', notification['notification_key'])
        self.assertEqual('Command Completed', notification['title'])
        self.assertTrue(notification['message'].startswith('Success · '))
        self.assertEqual(1, len(history.notifications))



class CommandNotifyNotificationProjectionTests(unittest.TestCase):
    def setUp(self):
        self.projector = NotificationEventProjector(
            history_store=Mock(),
            server=Mock(),
        )

    def test_success_event_projects_dedicated_device_event_notification(self):
        notification = self.projector._build_device_event({
            'client_id': 'client-1',
            'hostname': 'host-1',
            'kind': 'command.notify.finished',
            'data': {
                'status': 'success',
                'duration_ms': 12450,
                'history_entry_id': 'history-1',
            },
            'message': 'Success · 12.4s',
        })

        self.assertEqual('device_event', notification['notification_key'])
        self.assertEqual('Command Completed', notification['title'])
        self.assertEqual('Success · 12.4s', notification['message'])
        self.assertEqual('success', notification['type'])
        self.assertEqual('history-1', notification['context']['data']['history_entry_id'])

    def test_failed_event_projects_failed_notification(self):
        notification = self.projector._build_device_event({
            'client_id': 'client-1',
            'hostname': 'host-1',
            'kind': 'command.notify.finished',
            'data': {
                'status': 'failed',
                'duration_ms': 65320,
            },
            'message': 'Failed · 65.3s',
        })

        self.assertEqual('device_event', notification['notification_key'])
        self.assertEqual('Command Failed', notification['title'])
        self.assertEqual('Failed · 65.3s', notification['message'])
        self.assertEqual('error', notification['type'])


if __name__ == '__main__':
    unittest.main()
