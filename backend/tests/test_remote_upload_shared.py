"""Isolated contract tests for the two remote browser upload entry points."""
import ast
import hmac
import secrets
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

SERVER_DIR = Path(__file__).resolve().parents[1] / 'server'


class RemoteUploadContractTests(unittest.TestCase):
    def test_only_tracked_browser_upload_endpoint_remains(self):
        web = (SERVER_DIR / 'web' / 'routes' / 'command_execution.py').read_text()
        files = (SERVER_DIR / 'web' / 'file_transfer_app.py').read_text()
        self.assertNotIn("@blueprint.post('/api/connections/<client_id>/upload')", web)
        self.assertIn("@app.route('/api/transfers/browser-upload/<transfer_id>/content'", files)
        self.assertIn('command_execution_api.submit_web_upload(', files)
        self.assertIn("@blueprint.get('/api/upload-tmp/<temp_id>/<filename>')", web)

    def test_browser_upload_registration_creates_transfer_center_record(self):
        src = (SERVER_DIR / 'application' / 'web' / 'transfer_api.py').read_text()
        source = ast.parse(src)
        api = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'WebTransferApi')
        selected = [n for n in api.body if isinstance(n, ast.FunctionDef) and n.name in (
            '__init__', 'create_browser_upload_transfer')]
        isolated = ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
            name='WebTransferApi', bases=[], keywords=[], body=selected, decorator_list=[])], type_ignores=[]))
        env = {'hmac': hmac, 'secrets': secrets, 'threading': threading, 'WEB_FILE_TRANSFER_PORT': 8086}
        exec(compile(isolated, str(SERVER_DIR / 'application' / 'web' / 'transfer_api.py'), 'exec'), env)
        service = Mock()
        service.create_transfer.return_value = {'transfer_id': 'transfer-1', 'state': 'running'}
        instance = env['WebTransferApi'](service)
        created = instance.create_browser_upload_transfer(
            client_id='client-X', filename='test.zip', total_bytes=123,
            destination_path='/tmp/target', tab_id='tab-42')
        self.assertEqual(created['transfer_id'], 'transfer-1')
        self.assertEqual(created['browser_upload_port'], 8086)
        self.assertEqual(created['browser_upload_path'], '/api/transfers/browser-upload/transfer-1/content')
        self.assertTrue(created['browser_upload_token'])
        self.assertEqual(service.create_transfer.call_args.kwargs['tab_id'], 'tab-42')
        self.assertEqual(service.create_transfer.call_args.kwargs['metadata']['source'], 'remote_file_upload')
        self.assertEqual(service.create_transfer.call_args.kwargs['stage'], 'uploading_to_server')
        with self.assertRaisesRegex(ValueError, 'tab_id is required'):
            instance.create_browser_upload_transfer(client_id='c', filename='f', total_bytes=1)


if __name__ == '__main__':
    unittest.main()
