"""SystemExit/KeyboardInterrupt in remote Python must stay inside its task."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from client.commands.strategies.python_execution.inproc import InProcessPythonExecutionStrategy
from client.commands.strategies.python_execution.subprocess_pipe import SubprocessPipePythonExecutionStrategy
from client.jobs.core import subprocess_runner
from client.jobs.core.manager import JobManager


class InprocScriptExitBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.owner = Mock()
        self.owner._set_cancel_policy = Mock()
        self.strategy = InProcessPythonExecutionStrategy(self.owner)
        self.sdk_patches = [
            patch('client.commands.strategies.python_execution.inproc.build_script_sdk_globals', return_value={}),
            patch('client.commands.strategies.python_execution.inproc.use_script_sdk_context', return_value=contextlib.nullcontext()),
        ]
        for mocker in self.sdk_patches:
            mocker.start()
            self.addCleanup(mocker.stop)

    def test_sys_exit_zero_and_nonzero_are_failures_in_collect(self):
        for code in ('import sys; print("before"); sys.exit(0)',
                     'import sys; print("before"); sys.exit(7)',
                     'raise SystemExit("abort")',
                     'raise BaseException("unexpected base error")'):
            with self.subTest(code=code):
                status, output = self.strategy.execute_collect(code)
                self.assertEqual(status, 0)
                self.assertIn('BaseException:' if 'BaseException' in code else 'SystemExit:', output)
                if 'before' in code:
                    self.assertIn('before', output)

    def test_keyboard_interrupt_is_failure_in_collect(self):
        status, output = self.strategy.execute_collect('raise KeyboardInterrupt()')
        self.assertEqual(status, 0)
        self.assertIn('KeyboardInterrupt', output)

    def test_success_and_ordinary_exception_unchanged(self):
        self.assertEqual((1, 'ok\n'), self.strategy.execute_collect('print("ok")'))
        status, output = self.strategy.execute_collect('raise ValueError("bad")')
        self.assertEqual(status, 0)
        self.assertIn('ValueError: bad', output)

    def test_stream_exit_reports_failure_and_restores_streams(self):
        import sys
        before = (sys.stdout, sys.stderr)
        for code in ('import sys; print("pending", end=""); sys.exit(0)',
                     'raise KeyboardInterrupt()'):
            with self.subTest(code=code):
                self.owner.reset_mock()
                result = self.strategy.execute_stream(code)
                self.assertEqual(result[0], 0)
                errors = [call.args[1] for call in self.owner._send_interim_result.call_args_list
                          if call.args[0] == 0]
                self.assertTrue(any('SystemExit' in err or 'KeyboardInterrupt' in err for err in errors))
                self.owner._send_final_result.assert_not_called()
                self.assertEqual((sys.stdout, sys.stderr), before)
        messages = [call.args[1] for call in self.owner._send_interim_result.call_args_list]
        self.assertNotIn('Code execution completed', messages)

    def test_stream_success(self):
        self.strategy.execute_stream('print("ok")')
        self.owner._send_final_result.assert_called_once_with(1, 'Code execution completed')


class SubprocessScriptExitBoundaryTests(unittest.TestCase):
    def test_sys_exit_zero_and_keyboard_interrupt_return_task_failure(self):
        owner = Mock()
        owner._build_process_creation_kwargs.return_value = {}
        owner._resolve_timeout.return_value = 10
        strategy = SubprocessPipePythonExecutionStrategy(owner)
        for code in ('import sys; sys.exit(0)', 'import sys; sys.exit(None)', 'raise KeyboardInterrupt()'):
            with self.subTest(code=code):
                status, output = strategy.execute_collect(code)
                self.assertEqual(status, 0)
                self.assertIn('SystemExit' if 'sys.exit' in code else 'KeyboardInterrupt', output)

    def test_stream_sys_exit_zero_is_failure(self):
        owner = Mock()
        owner._build_process_creation_kwargs.return_value = {}
        owner._resolve_timeout.return_value = 10
        SubprocessPipePythonExecutionStrategy(owner).execute_stream('import sys; sys.exit(0)')
        owner._send_final_result.assert_called_once_with(0, 'Process exited with code 1')

    def test_successful_subprocess_script_remains_successful(self):
        owner = Mock()
        owner._build_process_creation_kwargs.return_value = {}
        owner._resolve_timeout.return_value = 10
        status, output = SubprocessPipePythonExecutionStrategy(owner).execute_collect('print("ok")')
        self.assertEqual((1, 'ok\n'), (status, output))


class SubprocessJobExitBoundaryTests(unittest.TestCase):
    def _run_main(self, job_instance=None, load_failure=None):
        context = {'job_key': 'sample', 'client_id': 'test-client'}
        with (patch.object(subprocess_runner, '_ensure_backend_on_path'),
              patch.object(subprocess_runner, '_parse_args', return_value=SimpleNamespace(context_file='unused')),
              patch.object(subprocess_runner, '_load_context', return_value=context),
              patch.object(subprocess_runner, '_start_control_reader', return_value=(None, None, None)),
              patch('client.runtime.sdk.context.use_script_sdk_context', return_value=contextlib.nullcontext()),
              patch.object(subprocess_runner, '_post_fallback_report') as fallback):
            with patch.object(subprocess_runner, '_load_job_instance') as load:
                if load_failure is not None:
                    load.side_effect = load_failure
                else:
                    load.return_value = job_instance
                result = subprocess_runner.main()
                return result, fallback

    def test_module_load_system_exit_is_not_success(self):
        for exc in (SystemExit(0), KeyboardInterrupt()):
            with self.subTest(exception=type(exc).__name__):
                result, fallback = self._run_main(load_failure=exc)
                self.assertEqual(result, 2)
                self.assertIn(type(exc).__name__, fallback.call_args.kwargs['text'])
                self.assertEqual(fallback.call_args.kwargs['state'], 'error')

    def test_normal_subprocess_job_completion_remains_stopped(self):
        instance = Mock()
        instance.is_running = True
        for attr in ('client_id', 'command_id', 'hostname', 'job_id', 'job_name', 'job_key'):
            setattr(instance, attr, 'test')
        result, _ = self._run_main(job_instance=instance)
        self.assertEqual(result, 0)
        instance.mark_stopped.assert_called_once()
        instance._report_state.assert_not_called()

    def test_run_exit_is_error_without_overwriting_with_stopped(self):
        for exc in (SystemExit(0), KeyboardInterrupt(), ValueError('failed')):
            with self.subTest(exception=type(exc).__name__):
                instance = Mock()
                instance.is_running = True
                instance.stop_event = Mock()
                instance.run.side_effect = exc
                for attr in ('client_id', 'command_id', 'hostname', 'job_id', 'job_name', 'job_key'):
                    setattr(instance, attr, 'test')
                result, _ = self._run_main(job_instance=instance)
                self.assertEqual(result, 1)
                instance._report_state.assert_called_once()
                self.assertEqual(instance._report_state.call_args.args[0], 'error')
                instance.mark_stopped.assert_not_called()
                instance.stop_event.set.assert_called_once()


class InprocJobExitBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.api_patches = [
            patch('client.jobs.core.manager.ClientApiClient'),
            patch('client.jobs.core.job.ClientApiClient'),
        ]
        for mocker in self.api_patches:
            mocker.start()
            self.addCleanup(mocker.stop)
        self.socket = SimpleNamespace(client_id='test-client', info={'hostname': 'test-host'})
        self.manager = JobManager(self.socket)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job_path = Path(self.tmp.name) / 'sample.py'

    def _write(self, source):
        self.job_path.write_text(source, encoding='utf-8')

    def _load(self):
        return self.manager._load_job_instance_from_file(
            str(self.job_path), 'sample', 17, job_metadata={},
            resolved_params={}, execution_mode='inproc',
        )

    def test_module_load_exit_or_keyboard_interrupt_converts_to_import_error(self):
        for code, name in [('import sys; sys.exit(0)', 'SystemExit'),
                           ('raise KeyboardInterrupt()', 'KeyboardInterrupt')]:
            with self.subTest(code=code):
                self._write(code)
                with self.assertRaisesRegex(ImportError, name):
                    self._load()

    def test_constructor_and_context_binding_exit_are_start_errors(self):
        for hook in ('__init__', 'on_context_bound'):
            with self.subTest(hook=hook):
                if hook == '__init__':
                    body = 'def __init__(self):\n        raise SystemExit(0)'
                else:
                    body = 'def on_context_bound(self):\n        raise KeyboardInterrupt()'
                self._write('from client.jobs.core.job import Job\n'
                            f'class Sample(Job):\n    {body}\n'
                            '    def run(self):\n        pass\n')
                with self.assertRaisesRegex(ImportError, 'SystemExit|KeyboardInterrupt'):
                    self._load()

    def test_running_job_exit_reports_error_without_escaping_thread(self):
        codes = [
            'import sys; sys.exit(0)',
            'raise KeyboardInterrupt()',
            'raise BaseException("unexpected base error")',
            'raise ValueError("ordinary error")',
        ]
        for code in codes:
            with self.subTest(code=code):
                self._write('from client.jobs.core.job import Job\n'
                            'class Sample(Job):\n'
                            '    def run(self):\n'
                            '        self.mark_running()\n'
                            f'        {code}\n')
                with patch.object(self.manager, '_resolve_job_definition', return_value=({}, {}, 'inproc')):
                    runtime = self.manager.start_job(str(self.job_path), 'sample', 17)
                runtime.thread.join(timeout=5)
                self.assertFalse(runtime.thread.is_alive())
                self.assertFalse(runtime.job_instance.is_running)
                self.assertTrue(runtime.job_instance.stop_event.is_set())
                reports = [call.args[0] for call in runtime.job_instance.client_api.post_background_job_report.call_args_list]
                self.assertTrue(any(p.get('state') == 'error' and p.get('status') == 0 for p in reports))
                self.assertTrue(any(p.get('event_type') == 'message' and p.get('status') == 0 for p in reports))
                runtime.job_instance.client_api.post_background_job_report.reset_mock()

    def test_successful_job_state_remains_unchanged(self):
        self._write('from client.jobs.core.job import Job\n'
                    'class Sample(Job):\n'
                    '    def run(self):\n'
                    '        self.mark_running()\n'
                    '        self.mark_stopped()\n')
        with patch.object(self.manager, '_resolve_job_definition', return_value=({}, {}, 'inproc')):
            runtime = self.manager.start_job(str(self.job_path), 'sample', 17)
        runtime.thread.join(timeout=5)
        self.assertFalse(runtime.thread.is_alive())
        reports = [call.args[0] for call in runtime.job_instance.client_api.post_background_job_report.call_args_list]
        self.assertTrue(any(p.get('state') == 'stopped' for p in reports))
        self.assertFalse(any(p.get('state') == 'error' for p in reports))


if __name__ == '__main__':
    unittest.main()
