"""Run the shipped Artifact SDK examples against the canonical Artifact contract.

The HTTP boundary is stubbed; the SDK and each Script's source execute unchanged.
"""
import runpy
import uuid
from pathlib import Path

import pytest

from client.http.client_api import ClientApiClient
from client.runtime.sdk import artifact


SCRIPTS = Path(__file__).resolve().parents[1] / 'server/resources/scripts/test/sdk/artifact'


@pytest.mark.parametrize('script', ['test_save', 'test_get', 'test_find', 'test_list', 'test_download'])
def test_artifact_sdk_script_uses_current_saved_type(script, monkeypatch, capsys):
    records = {}
    upload_forms = []

    class UploadResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return {'code': 0, 'data': self.payload}

    def upload(_client, source, *, filename='', form_data=None, **_kwargs):
        assert form_data['artifact_type'] == 'saved'
        assert form_data['category'] == 'script_files'
        data = Path(source).read_bytes()
        artifact_id = uuid.uuid4().hex
        item = {'artifact_id': artifact_id, 'original_name': filename,
                'artifact_type': 'saved', 'category': 'script_files', 'size': len(data),
                'download_url': f'/api/artifacts/{artifact_id}/download'}
        records[artifact_id] = (item, data)
        upload_forms.append(form_data)
        return UploadResponse(item)

    def list_artifacts(_client, params, *, timeout=15):
        assert params.get('type') == 'saved'
        return {'items': [item for item, _data in records.values()]}

    def download(_client, url, destination, **_kwargs):
        artifact_id = url.split('/')[3]
        Path(destination).write_bytes(records[artifact_id][1])

    monkeypatch.setattr(ClientApiClient, 'upload_file_source', upload)
    monkeypatch.setattr(ClientApiClient, 'list_artifacts', list_artifacts)
    monkeypatch.setattr(ClientApiClient, 'download_file', download)
    monkeypatch.setattr(artifact, 'get_execution_owner', lambda: None)
    if script == 'test_list':
        # This example queries without creating its own Artifact.
        records['existing'] = ({'artifact_id': 'existing', 'original_name': 'example.txt',
                                'artifact_type': 'saved'}, b'')

    runpy.run_path(str(SCRIPTS / f'{script}.py'))
    assert 'PASS' in capsys.readouterr().out
    if script != 'test_list':
        assert len(upload_forms) == 1
