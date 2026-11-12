"""Web command/upload correlation must not change execution or history ownership."""

import importlib.util
from pathlib import Path
import sys
import types
from unittest import TestCase
from unittest.mock import Mock, patch

from server.application.tasks.task_service import WebTaskService
from server.application.web.command_execution_api import WebCommandExecutionApi


class OperationCorrelationTests(TestCase):
    def test_web_upload_passes_uuid_to_task_metadata(self):
        task = Mock()
        task.submit_web_upload.return_value = {'task_id': 'task-1'}
        api = WebCommandExecutionApi(task)
        identifier = '7cd4bb58-99b5-4fa7-9f22-fbd877ab0c95'
        result = api.submit_web_upload('device', '/temp/file', 'file', '/home', operation_id=identifier)
        self.assertEqual(result['task_id'], 'task-1')
        self.assertEqual(task.submit_web_upload.call_args.kwargs['operation_id'], identifier)
        service = WebTaskService(Mock(), Mock(), Mock(), Mock())
        with patch.object(service, '_submit_request', side_effect=lambda request: request) as submit:
            request = service.submit_web_upload('device', '/tmp/a', 'a', operation_id=identifier)
            self.assertEqual(request.metadata['operation_id'], identifier)
            self.assertEqual(request.metadata['display_name'], 'a')
            self.assertEqual(submit.call_count, 1)

    def test_history_records_business_metadata_without_browser_runtime_id(self):
        identifier = '7cd4bb58-99b5-4fa7-9f22-fbd877ab0c95'
        server = Mock()
        server.command_adapter.prepare_command.return_value = 'entry-1'
        task_store = Mock()
        task_store.create_task.return_value = {'task_id': 'task-1'}
        service = WebTaskService(server, task_store, Mock(), Mock())
        from server.application.tasks.task_service import WebExecutionTaskRequest
        request = WebExecutionTaskRequest(client_id='device', command='echo hi',
            task_type='command', runner_name='run_command_task',
            metadata={'operation_id': identifier, 'script_run': True})
        task = service._create_task_with_history(Mock(), request)
        self.assertEqual(task['history_entry_id'], 'entry-1')
        metadata = server.command_adapter.prepare_command.call_args.kwargs['metadata']
        self.assertEqual(metadata, {'script_run': True})
        self.assertEqual(request.metadata['operation_id'], identifier)

    def test_header_rejects_malformed_uuid_before_task_creation(self):
        fake_flask = types.ModuleType('flask')
        fake_flask.request = types.SimpleNamespace(headers={})
        code = Path(__file__).resolve().parents[2] / 'server' / 'web' / 'operation_id.py'
        spec = importlib.util.spec_from_file_location('operation_header_for_tests', code)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'flask': fake_flask}):
            spec.loader.exec_module(module)
            self.assertEqual(module.get_optional_operation_id(), '')
            fake_flask.request.headers['X-RCH-Operation-ID'] = '7cd4bb58-99b5-4fa7-9f22-fbd877ab0c95'
            self.assertEqual(module.get_optional_operation_id(), '7cd4bb58-99b5-4fa7-9f22-fbd877ab0c95')
            for invalid in ['[Artifact Send]', '../../path', 'x' * 100, '7cd4bb5899b54fa79f22fbd877ab0c95']:
                fake_flask.request.headers['X-RCH-Operation-ID'] = invalid
                with self.assertRaisesRegex(ValueError, 'Invalid operation ID'):
                    module.get_optional_operation_id()
