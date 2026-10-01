import unittest
from types import SimpleNamespace

from client.commands.common.services.transfer.http_file_transfer_service import (
    CommandHttpFileTransferService,
)


class HttpUploadTerminalOutputTests(unittest.TestCase):
    def setUp(self):
        owner = SimpleNamespace(socket=SimpleNamespace(client_id='client-1'), command_id=7)
        self.service = CommandHttpFileTransferService(owner)

    def test_upload_start_message_is_compact_and_human_readable(self):
        self.assertEqual(
            'Uploading: screenshot.png (1.71 MB)',
            self.service.build_http_upload_start_message('/tmp/screenshot.png', 1796001),
        )
        self.assertEqual(
            'Uploading: studio.db (188 KB)',
            self.service.build_http_upload_start_message('/Users/flc/studio/studio.db', 192512),
        )

    def test_upload_success_message_has_no_internal_artifact_fields_or_generic_ok(self):
        payload = {
            'message': 'ok',
            'data': {
                'original_name': 'studio.db',
                'stored_name': 'studio_abc.db',
                'artifact_id': 'artifact-123',
                'download_url': '/api/artifacts/artifact-123/download',
            },
        }

        message = self.service.build_http_upload_success_message(
            payload,
            file_path='/Users/flc/studio/studio.db',
            fallback_message='HTTP upload completed',
        )

        self.assertEqual('[+] Upload completed: studio.db', message)
        self.assertNotIn('Original:', message)
        self.assertNotIn('Stored:', message)
        self.assertNotIn('Artifact ID:', message)
        self.assertNotIn('Download URL:', message)
        self.assertNotEqual('[+] ok', message)


if __name__ == '__main__':
    unittest.main()
