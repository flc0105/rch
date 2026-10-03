import tempfile
import unittest
from types import ModuleType, SimpleNamespace

import importlib
import sys

from core.utils.job_metadata import normalize_job_key
from server.application.artifact.artifact_reference_view_projector import ArtifactReferenceViewProjector
from server.application.history.history_write_service import HistoryWriteService
from server.models.artifact import ArtifactReference


class _ArtifactService:
    def __init__(self, artifact=None, error=None):
        self.artifact = artifact
        self.error = error

    def get_artifact_by_id(self, artifact_id):
        if self.error:
            raise self.error
        if not self.artifact or self.artifact.get('artifact_id') != artifact_id:
            raise FileNotFoundError(artifact_id)
        return dict(self.artifact)


class _UploadApi:
    def __init__(self):
        self.calls = []

    def save_http_uploaded_file(self, upload, **kwargs):
        self.calls.append((upload, kwargs))
        return {'artifact_id': 'artifact-1', 'original_name': upload.filename}


class _HistoryStore:
    def __init__(self):
        self._lock = _NullContext()
        self.database = SimpleNamespace(transaction=lambda: _NullContext())
        self.entries = {
            ('machine-1', 'entry-1'): {
                'files': [],
                'updated_at': '',
            }
        }

    @staticmethod
    def _get_machine_id_from_conn(_conn):
        return 'machine-1'

    @staticmethod
    def _now_iso():
        return '2026-10-02T22:00:00'

    def _get_entry(self, machine_id, entry_id):
        return self.entries.get((machine_id, entry_id))

    @staticmethod
    def _update_entry(_entry):
        return None

    @staticmethod
    def _update_recent_snapshot_if_present(_entry):
        return None


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class ArtifactJobUploadRefactorTests(unittest.TestCase):
    def test_artifact_reference_keeps_persisted_reference_fields_only(self):
        payload = {
            'artifact_id': 'a1',
            'artifact_type': 'files',
            'category': 'default',
            'hostname': 'mac',
            'machine_id': 'm1',
            'client_id': 'c1',
            'original_name': 'demo.txt',
            'stored_name': 'demo_hash.txt',
            'saved_path': '/tmp/demo_hash.txt',
            'size': 12,
            'created_at': '2026-10-02 10:00:00',
            'download_url': '/download',
            'raw_url': '/raw',
            'preview_url': '/preview',
            'is_available': False,
            'status_text': 'view-only',
            '_meta_path': '/tmp/meta.json',
        }
        reference = ArtifactReference.from_dict(payload).to_dict()
        self.assertEqual('a1', reference['artifact_id'])
        self.assertEqual('/tmp/demo_hash.txt', reference['saved_path'])
        self.assertNotIn('is_available', reference)
        self.assertNotIn('status_text', reference)
        self.assertNotIn('_meta_path', reference)

    def test_history_write_persists_shared_artifact_reference(self):
        store = _HistoryStore()
        service = HistoryWriteService(store)
        conn = object()
        service.append_file_for_connection(conn, 'entry-1', {
            'artifact_id': 'a1',
            'original_name': 'demo.txt',
            'saved_path': '/tmp/demo.txt',
            'is_available': True,
            'status_text': 'transient',
        })
        saved = store.entries[('machine-1', 'entry-1')]['files'][0]
        self.assertEqual('a1', saved['artifact_id'])
        self.assertNotIn('is_available', saved)
        self.assertNotIn('status_text', saved)

    def test_projector_resolves_history_and_job_path_policies(self):
        artifact = {
            'artifact_id': 'a1',
            'artifact_type': 'files',
            'category': 'default',
            'hostname': '',
            'machine_id': 'm1',
            'client_id': 'c1',
            'original_name': 'demo.txt',
            'stored_name': 'demo_hash.txt',
            'saved_path': '/artifacts/demo_hash.txt',
            'size': 99,
            'created_at': '2026-10-02 10:00:00',
            'download_url': '/download',
            'raw_url': '/raw',
            'preview_url': '/preview',
            'is_available': True,
            'status_text': '',
        }
        projector = ArtifactReferenceViewProjector()
        service = _ArtifactService(artifact)

        history_view = projector.project(
            {'artifact_id': 'a1', 'hostname': 'old', 'saved_path': '/old'},
            service,
            path_key='saved_path',
            allow_local_path_fallback=True,
            include_created_at=True,
        )
        self.assertEqual('', history_view['hostname'])
        self.assertEqual('/artifacts/demo_hash.txt', history_view['saved_path'])
        self.assertEqual('2026-10-02 10:00:00', history_view['created_at'])
        self.assertTrue(history_view['is_available'])

        job_view = projector.project(
            {'association_id': 7, 'artifact_id': 'a1', 'time': 'event-time'},
            service,
            path_key='relative_path',
        )
        self.assertEqual(7, job_view['association_id'])
        self.assertEqual('/artifacts/demo_hash.txt', job_view['relative_path'])
        self.assertNotIn('saved_path', job_view)
        self.assertNotIn('created_at', job_view)

    def test_projector_preserves_history_local_fallback_only(self):
        projector = ArtifactReferenceViewProjector()
        with tempfile.NamedTemporaryFile() as file_obj:
            history_view = projector.project(
                {'saved_path': file_obj.name},
                None,
                path_key='saved_path',
                allow_local_path_fallback=True,
            )
            self.assertTrue(history_view['is_available'])
            self.assertEqual('', history_view['status_text'])

        job_view = projector.project(
            {'relative_path': '/tmp/anything'},
            None,
            path_key='relative_path',
            allow_local_path_fallback=False,
        )
        self.assertFalse(job_view['is_available'])
        self.assertEqual('Artifact removed', job_view['status_text'])

    def test_projector_marks_missing_artifact_without_changing_existing_identity(self):
        projector = ArtifactReferenceViewProjector()
        view = projector.project(
            {'artifact_id': 'missing', 'original_name': 'old.txt'},
            _ArtifactService(error=FileNotFoundError('missing')),
        )
        self.assertEqual('old.txt', view['original_name'])
        self.assertFalse(view['is_available'])
        self.assertEqual('Artifact removed', view['status_text'])

    def test_normalize_job_key_is_shared_and_path_safe(self):
        self.assertEqual('new_job', normalize_job_key('new_job.py'))
        self.assertEqual('new_job', normalize_job_key('jobs/new_job.py'))
        self.assertEqual('new_job', normalize_job_key(r'jobs\\new_job.py'))
        self.assertEqual('', normalize_job_key(''))

    def test_shared_http_upload_parser_preserves_all_fields(self):
        class _Upload:
            filename = 'demo.txt'

        values = {
            'artifact_type': 'files',
            'category': 'tests',
            'client_id': 'client-1',
            'hostname': 'mac',
            'machine_id': 'machine-1',
            'job_id': 'job-1',
            'job_name': 'demo_job',
            'job_key': 'demo_job',
        }
        ints = {'source_command_id': 42, 'transfer_buffer_size': 65536}
        fake_parsers = ModuleType('server.web.request_parsers')
        fake_parsers.get_required_upload = lambda: _Upload()
        fake_parsers.get_optional_form_text = lambda name, default='': values.get(name, default)
        fake_parsers.parse_optional_int_form = lambda name: ints.get(name)
        fake_parsers.parse_optional_json_form = lambda name: {'kind': 'smoke'} if name == 'extra' else {}

        old_parsers = sys.modules.get('server.web.request_parsers')
        old_upload = sys.modules.pop('server.web.artifact_upload', None)
        sys.modules['server.web.request_parsers'] = fake_parsers
        try:
            module = importlib.import_module('server.web.artifact_upload')
            api = _UploadApi()
            result = module.save_uploaded_artifact_from_request(api)
        finally:
            sys.modules.pop('server.web.artifact_upload', None)
            if old_upload is not None:
                sys.modules['server.web.artifact_upload'] = old_upload
            if old_parsers is None:
                sys.modules.pop('server.web.request_parsers', None)
            else:
                sys.modules['server.web.request_parsers'] = old_parsers

        self.assertEqual('artifact-1', result['artifact_id'])
        self.assertEqual(1, len(api.calls))
        upload, kwargs = api.calls[0]
        self.assertEqual('demo.txt', upload.filename)
        self.assertEqual('tests', kwargs['category'])
        self.assertEqual('client-1', kwargs['client_id'])
        self.assertEqual(42, kwargs['source_command_id'])
        self.assertEqual(65536, kwargs['transfer_buffer_size'])
        self.assertEqual({'kind': 'smoke'}, kwargs['extra'])



if __name__ == '__main__':
    unittest.main()
