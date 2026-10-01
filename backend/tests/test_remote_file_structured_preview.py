import unittest
from types import SimpleNamespace

from client.transfers.manager import ClientTransferManager
from core.protocol.message_types import MSG_TYPE_TRANSFER_START
from server.application.artifact.remote_file_service import WebRemoteFileService


class _FakeTransferService:
    def __init__(self):
        self.created = []
        self.failed = []
        self.item = None

    def create_transfer(self, **kwargs):
        self.created.append(kwargs)
        self.item = {
            'transfer_id': 'transfer-1',
            'state': 'running',
            **kwargs,
        }
        return dict(self.item)

    def wait_for_terminal(self, transfer_id):
        self.item.update({
            'state': 'completed',
            'stage': 'completed',
            'artifact_id': 'artifact-1',
        })
        return dict(self.item)

    def get_transfer(self, transfer_id):
        return dict(self.item) if self.item else None

    def fail_transfer(self, transfer_id, error, *, client_id=''):
        self.failed.append((transfer_id, error, client_id))
        if self.item:
            self.item.update({'state': 'failed', 'error': error})


class _FakeSession:
    def __init__(self):
        self.session_info = SimpleNamespace(hostname='mac.local')
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


class _FakeRemoteExecutionService:
    def __init__(self, session):
        self.session = session
        self.foreground_calls = []

    def get_connection(self, client_id):
        return self.session

    def run_foreground_text_command(self, *args, **kwargs):
        self.foreground_calls.append((args, kwargs))
        raise AssertionError('preview_file must not parse foreground command text')


class _FakeArtifactService:
    def get_artifact_by_id(self, artifact_id):
        return {
            'artifact_id': artifact_id,
            'original_name': 'photo.png',
        }

    def build_preview_payload(self, artifact_id):
        return {'type': 'image', 'artifact_id': artifact_id}


class RemoteFileStructuredPreviewTests(unittest.TestCase):
    def test_preview_uses_structured_transfer_and_artifact_id(self):
        session = _FakeSession()
        execution = _FakeRemoteExecutionService(session)
        transfers = _FakeTransferService()
        service = WebRemoteFileService(
            execution,
            _FakeArtifactService(),
            transfer_service=transfers,
        )

        result = service.preview_file(
            'client-1',
            '/Users/flc/Pictures/photo.png',
            tab_id='tab-1',
        )

        self.assertEqual({'type': 'image', 'artifact_id': 'artifact-1'}, result)
        self.assertEqual([], execution.foreground_calls)
        self.assertEqual('remote_file_preview', transfers.created[0]['metadata']['source'])
        self.assertEqual('tab-1', transfers.created[0]['tab_id'])
        self.assertEqual(1, len(session.sent))
        self.assertEqual(MSG_TYPE_TRANSFER_START, session.sent[0]['type'])
        self.assertEqual('client_to_server_preview', session.sent[0]['operation'])
        self.assertEqual(
            {'path': '/Users/flc/Pictures/photo.png'},
            session.sent[0]['payload'],
        )


class ClientTransferPreviewTests(unittest.TestCase):
    def test_preview_operation_preserves_preview_image_preparation_and_cleanup(self):
        manager = ClientTransferManager.__new__(ClientTransferManager)
        prepared = SimpleNamespace(
            upload_path='/tmp/photo_preview.jpg',
            extra={'compress': True, 'quality': 75},
        )
        cleanup_calls = []
        upload_calls = []

        owner = SimpleNamespace(
            path_resolver=SimpleNamespace(
                require_existing_file_from_arg=lambda path: '/Users/flc/Pictures/photo.png'
            ),
            preview_image_service=SimpleNamespace(
                prepare_upload_file=lambda path: prepared,
                cleanup_upload_file=lambda item: cleanup_calls.append(item),
            ),
        )

        class _Service:
            def upload_single_file_to_server_result(self, path, **kwargs):
                upload_calls.append((path, kwargs))
                return 1, 'done'

        manager._run_client_to_server_preview(
            _Service(),
            owner,
            'transfer-1',
            {'path': '/Users/flc/Pictures/photo.png'},
        )

        self.assertEqual('/tmp/photo_preview.jpg', upload_calls[0][0])
        self.assertEqual('previews', upload_calls[0][1]['artifact_type'])
        self.assertEqual('preview_cache', upload_calls[0][1]['category'])
        self.assertEqual({'compress': True, 'quality': 75}, upload_calls[0][1]['extra'])
        self.assertEqual('transfer-1', upload_calls[0][1]['transfer_id'])
        self.assertEqual([prepared], cleanup_calls)


if __name__ == '__main__':
    unittest.main()
