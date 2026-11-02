"""Server-owned Job reports, shared completion and remote CLI pass-through."""
import io
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'rchcli'))

from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.command.job_builtin_support import JobBuiltinSupport
import server.application.command.job_builtin_support as job_module
import rchcli


class JobApi:
    def __init__(self):
        self.details = 0
        self.jobs = [
            {'job_id': 'new-id', 'job_key': 'clip', 'job_name': 'clipboard_monitor', 'state': 'running'},
            {'job_id': 'old-id', 'job_key': 'clip', 'job_name': 'clipboard_monitor', 'state': 'stopped'},
            {'job_id': 'other-id', 'job_key': 'other', 'job_name': 'other', 'state': 'stopped'},
        ]
        self.output = [
            {'seq': 1, 'status': 1, 'text': 'hello'},
            {'seq': 2, 'status': 0, 'text': 'failure report'},
        ]
        self.state = 'running'
    def list_background_jobs(self, client_id):
        assert client_id == 'client-A'
        return self.jobs
    def get_background_job(self, client_id, job_id):
        assert client_id == 'client-A' and job_id in ('new-id', 'old-id', 'other-id')
        self.details += 1
        return dict(job_id=job_id, job_key='clip', state=self.state, messages=list(self.output))


class JobServerTests(unittest.TestCase):
    def setUp(self):
        self.api = JobApi()
        self.task = dict(cancel_requested=False, command_id=None)
        self.conn = SimpleNamespace(
            session_info=SimpleNamespace(client_id='client-A'),
            get_foreground_task=lambda: self.task,
        )
        self.server = SimpleNamespace(web_service=SimpleNamespace(job_api=self.api))
        self.support = JobBuiltinSupport(self.server, self.conn, None)

    def run_builtin(self, args):
        return list(self.support.job(args))

    def test_registry_and_help_are_server_owned(self):
        registry = SERVER_COMMAND_REGISTRY
        self.assertEqual(registry.parse('job', 'logs clip --follow')[1:], ('logs', 'clip --follow'))
        self.assertIn('job logs <name>', registry.help('job'))
        self.assertIn('job logs <name>', registry.help('job logs'))
        self.assertEqual(registry.parse('job', 'start clip')[1], 'start')

    def test_once_latest_job_and_historical_error_does_not_fail_query(self):
        events = self.run_builtin('logs clipboard_monitor')
        self.assertIn('new-id', events[0][1])
        self.assertEqual(events[1:], [(1, 'hello'), (1, '[error] failure report')])
        self.assertEqual(self.api.details, 1)
        self.assertFalse(any(status == 0 for status, _ in events))

    def test_bad_arguments_and_missing_job(self):
        for args in ['logs', 'logs clip no', 'logs clip --unknown', 'logs clip -f -f', 'logs clip --follow -f']:
            with self.subTest(args=args):
                self.assertEqual(self.run_builtin(args)[0][0], 0)
        self.assertIn('No reported Job', self.run_builtin('logs nowhere')[0][1])

    def test_follow_deduplicates_and_finishes_without_local_interception(self):
        def fake_sleep(_):
            if self.api.details == 1:
                self.api.output.append({'seq': 3, 'status': 1, 'text': 'new report'})
                self.api.state = 'stopped'
        with patch.object(job_module.time, 'sleep', fake_sleep):
            events = self.run_builtin('logs clip -f')
        self.assertEqual(sum(text == 'new report' for _, text in events), 1)
        self.assertEqual(events[-1], (1, '[Job finished]'))
        self.assertEqual(self.api.details, 2)

    def test_follow_cancel_is_server_task_cancel_not_job_stop(self):
        def fake_sleep(_):
            self.task['cancel_requested'] = True
        with patch.object(job_module.time, 'sleep', fake_sleep):
            events = self.run_builtin('logs clip --follow')
        self.assertEqual(events[-1], (0, 'command cancelled'))
        self.assertEqual(self.api.details, 1)

    def test_command_execution_pipeline_streams_and_honors_cancel(self):
        from server.application.command.command_execution_pipeline import CommandExecutionPipeline
        from server.application.command.command_execution_event import CommandExecutionEvent
        from server.application.tasks.task_status import TaskStreamSummary, WebTaskStatus

        class Executor:
            def process_command(_, command, history_entry_id=''):
                self.assertEqual(command, 'job logs clip --follow')
                return lambda: self.support.job('logs clip --follow')
        ctx = SimpleNamespace(command='job logs clip --follow', source='rch_cli',
                              task_id='t-1', history_entry_id='h-1', session=self.conn)
        def fake_sleep(_):
            self.task['cancel_requested'] = True
        with patch.object(job_module.time, 'sleep', fake_sleep):
            events = list(CommandExecutionPipeline(None).iter_events(
                ctx, Executor(), finalize_history=False))
        chunks = [event for event in events if event.event_type == CommandExecutionEvent.CHUNK]
        self.assertTrue(any(event.text == 'hello' for event in chunks))
        errors = [event for event in events if event.event_type == CommandExecutionEvent.ERROR]
        self.assertEqual([event.text for event in errors], ['command cancelled'])
        summary = TaskStreamSummary()
        for event in chunks:
            summary.record_chunk(event.status, event.text)
        for event in errors:
            summary.record_chunk(event.status, event.text)
        self.assertEqual(summary.resolve_final_status(cancel_requested=True), WebTaskStatus.CANCELLED)

    def test_follow_existing_terminal_job_returns_without_polling(self):
        self.api.state = 'stopped'
        self.assertEqual(self.run_builtin('logs clip --follow')[-1], (1, '[Job finished]'))
        self.assertEqual(self.api.details, 1)

    def test_cli_forwards_logs_raw_like_other_server_job_commands(self):
        class Api:
            def connections(self):
                return [{'client_id': 'client-A', 'hostname': 'Linux', 'connection_state': 'online',
                         'connected_at': '2026-11-02T10:00:00'}]
        commands = iter(['0', 'job logs clip -f', 'bg', 'quit'])
        cli = rchcli.RemoteConsole(Api(), object(), 'tab-id', output=io.StringIO(),
                                   reader=lambda prompt: next(commands), color='never')
        executed = []
        cli.execute = executed.append
        cli.repl()
        self.assertEqual(executed, ['job logs clip -f'])
        self.assertFalse(hasattr(Api(), 'background_jobs'))
        self.assertFalse((ROOT / 'rchcli/rchcli_jobs.py').exists())


class JobCompletionTests(unittest.TestCase):
    def test_shared_server_provider(self):
        import ast
        source = (ROOT / 'server/application/completion/command_completion_providers.py').read_text()
        cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef)
                   and node.name == 'JobCommandCompletionProvider')
        from core.command_completion.models import CompletionCandidate, CompletionContext
        from core.command_completion.provider import CommandCompletionProvider
        class Mixin:
            def __init__(self, server): self.server = server
            def get_client_id(self, ctx): return ctx.metadata.get('client_id')
            def get_client_platform(self, ctx): return 'mac'
        scope = {'ServerCompletionSessionMixin': Mixin,
                 'CommandCompletionProvider': CommandCompletionProvider,
                 'CompletionCandidate': CompletionCandidate, 'CompletionContext': CompletionContext,
                 'visible_on_platform': lambda item, platform: platform in item.get('platforms', [])}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), '<provider>', 'exec'), scope)
        class Api:
            def list_background_job_catalog(self, client_id):
                return [{'job_name': 'alpha', 'platforms': ['mac']},
                        {'job_name': 'win_only', 'platforms': ['win']}]
            def list_background_jobs(self, client_id):
                return [{'job_key': 'alpha', 'state': 'running'},
                        {'job_key': 'beta', 'state': 'stopping'},
                        {'job_key': 'old', 'state': 'stopped'}]
        provider = scope['JobCommandCompletionProvider'](SimpleNamespace(web_service=SimpleNamespace(job_api=Api())))
        for action, expected in [('start', ['alpha']), ('stop', ['alpha','beta']),
                                 ('status', ['alpha', 'beta']), ('logs', ['alpha', 'beta', 'old'])]:
            with self.subTest(action=action):
                ctx = CompletionContext(command_name='job', argument_text=action + ' ',
                                        metadata={'client_id': 'client-A'})
                self.assertEqual([item.name for item in provider.complete(ctx)], expected)
        ctx = CompletionContext(command_name='job', argument_text='logs old --follow ',
                                metadata={'client_id': 'client-A'})
        self.assertEqual(provider.complete(ctx), [])

if __name__ == '__main__':
    unittest.main()
