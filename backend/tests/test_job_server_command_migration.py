"""Job public CLI is Server-owned; Client receives only internal job_control RPC."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from client.jobs.command_control import ClientJobControl
from core.utils.job_control_result import decode_job_control_result, encode_job_control_result
from core.protocol.message_router_base import BaseMessageRouter
from core.protocol.message_types import MSG_TYPE_JOB_CONTROL
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.application.command.job_builtin_support import JobBuiltinSupport
from server.application.jobs.background_job_service import BackgroundJobService
from server.application.web.job_api import WebJobApi


class JobCommandMigrationTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.remote = SimpleNamespace(stream_command=self.stream_command)
        self.jobs = SimpleNamespace(
            list_background_job_catalog=lambda _cid: [{'job_name': 'tools/a', 'metadata': {'platforms': ['common']}}],
            prepare_background_job_start=lambda _cid, _name, _mode: 'inproc',
        )
        self.jobs.background_job_service = SimpleNamespace(
            _build_job_control_command=lambda action, **payload: json.dumps({'action': action, **payload})
        )
        self.server = SimpleNamespace(web_service=SimpleNamespace(job_api=self.jobs))
        self.conn = SimpleNamespace(session_info=SimpleNamespace(client_id='c1'))
        self.svc = JobBuiltinSupport(self.server, self.conn, self.remote)

    def stream_command(self, target, text, *, command_type, history_entry_id=''):
        self.assertIs(target, self.conn)
        payload = json.loads(text)
        self.sent.append((payload, command_type))
        if payload['action'] in {'start','stop','stop_all'}:
            yield (1, encode_job_control_result(payload['action'], 'accepted',
                                                total=0 if payload['action'] == 'stop_all' else 1,
                                                succeeded=0 if payload['action'] == 'stop_all' else 1))
        else:
            yield (1, 'accepted')

    def test_server_list_never_contacts_client(self):
        self.assertEqual([(1, 'tools/a')], list(self.svc.job('list')))
        self.assertEqual([], self.sent)

    def test_server_routes_start_and_controls_using_internal_protocol(self):
        for cmd, expected in [
            ('start tools/a', 'start'), ('ps', 'ps'),
            ('status tools/a', 'status'), ('stop tools/a', 'stop'),
            ('stop-all', 'stop_all'),
        ]:
            self.assertEqual([(1, 'accepted')], list(self.svc.job(cmd)))
            self.assertEqual((expected, MSG_TYPE_JOB_CONTROL),
                             (self.sent[-1][0]['action'], self.sent[-1][1]))

    def test_invalid_job_request_does_not_dispatch(self):
        self.assertEqual(0, list(self.svc.job('start'))[0][0])
        self.assertEqual(0, list(self.svc.job('start demo --params []'))[0][0])
        self.assertEqual(0, list(self.svc.job('unknown'))[0][0])
        self.assertFalse(self.sent)

    def test_old_client_public_job_commands_not_exported(self):
        from client.commands.common.groups import CommonRuntimeCommands
        for name in ('start_job', 'stop_job', 'jobs', 'jobs_ps', 'job_status', 'stop_all_jobs'):
            method = getattr(CommonRuntimeCommands, name, None)
            self.assertFalse(getattr(method, 'help', None), name)

    def test_client_internal_job_dispatch_and_status(self):
        runtime = SimpleNamespace(
            job_manager=SimpleNamespace(
                list_running_jobs=lambda: ['tools/a'],
                get_job_status=lambda key: {'job_key': key, 'state': 'running'},
                stop_job=lambda key: SimpleNamespace(display_name=key, job_id='job-1'),
                stop_all_jobs=lambda: {'total':1, 'stopped':[{'display_name':'tools/a','job_id':'job-1'}], 'errors':[]},
            ),
        )
        commands = SimpleNamespace(socket=SimpleNamespace(runtime=runtime))
        self.assertEqual((1, 'tools/a'), ClientJobControl.execute(commands, '{"action":"ps"}'))
        self.assertIn('running', ClientJobControl.execute(commands, '{"action":"status","job_key":"tools/a"}')[1])
        status, wire = ClientJobControl.execute(commands, '{"action":"stop","job_key":"tools/a"}')
        self.assertEqual(1, status)
        self.assertEqual('job-1', decode_job_control_result(wire, 'stop')['job_id'])
        self.assertEqual(1, ClientJobControl.execute(commands, '{"action":"stop_all"}')[0])
        self.assertEqual(0, ClientJobControl.execute(commands, '{"action":"bogus"}')[0])

    def test_client_job_start_keeps_jobmanager_and_download(self):
        with TemporaryDirectory() as folder:
            runtime = SimpleNamespace(display_name='tools/a', job_key='tools/a', job_id='uuid-1', execution_mode='inproc', worker_name='worker')
            manager = SimpleNamespace(start_job=Mock(return_value=runtime))
            context = SimpleNamespace(runtime=SimpleNamespace(job_manager=manager))
            commands = SimpleNamespace(
                socket=context,
                command_id=7,
                client_api=SimpleNamespace(download_job=lambda name, timeout: 'print("ok")'),
                _send_interim_result=Mock(),
            )
            with patch('client.jobs.command_control.make_client_temp_dir', return_value=folder):
                status, text = ClientJobControl.execute(commands, json.dumps({
                    'action':'start', 'job_name':'tools/a', 'params':{}, 'execution_mode':'inproc',
                }))
            self.assertEqual(1, status)
            self.assertIn('job stop tools/a', decode_job_control_result(text, 'start')['message'])
            self.assertEqual('tools/a', manager.start_job.call_args.args[1])
            self.assertEqual(7, manager.start_job.call_args.args[2])
            self.assertTrue(Path(folder, 'remote_job.py').is_file())

    def test_web_job_service_uses_internal_message_type(self):
        class FakeRemote:
            def __init__(self):
                self.kwargs = None
            def get_connection(self, cid):
                return SimpleNamespace(session_info=SimpleNamespace(machine_id='m1', client_id=cid))
            def stream_foreground_command(self, target, command, **kwargs):
                self.kwargs = kwargs
                action = json.loads(command)['action']
                yield 1, encode_job_control_result(action, 'OK', job_id='j1')
            def collect_result(self, it):
                return list(it)[-1]
        remote = FakeRemote()
        service = BackgroundJobService(None, None, remote, None)
        service.start_job('client', 'example')
        self.assertEqual('job_control', remote.kwargs['command_type'])
        service.stop_job('client', 'example')
        self.assertEqual('job_control', remote.kwargs['command_type'])

    def test_builtin_registration_and_dispatch(self):
        names = {item['name'] for item in BuiltinCommandHandler.REGISTRY.candidates()}
        self.assertIn('job', names)
        self.assertNotIn('start_job', names)
        self.assertNotIn('stop_job', names)


if __name__ == '__main__':
    unittest.main()
