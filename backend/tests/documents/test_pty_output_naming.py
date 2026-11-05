"""PTY toolbar export reuses Command Output Artifact allocation and naming."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from server.application.artifact.command_output_artifact_service import CommandOutputArtifactService


def test_pty_toolbar_export_uses_timestamped_command_output_artifact(tmp_path):
    allocated = []
    registered = []

    def allocate_artifact_path(**kwargs):
        allocated.append(kwargs)
        return {
            'file_path': str(tmp_path / kwargs['original_name']),
            'meta_path': str(tmp_path / 'metadata.json'),
            'stored_name': kwargs['original_name'],
            'machine_id': kwargs['machine_id'],
        }

    def register_existing_artifact(**kwargs):
        registered.append(kwargs)
        return {'artifact_id': 'A', 'original_name': kwargs['original_name']}

    service = CommandOutputArtifactService(SimpleNamespace(
        allocate_artifact_path=allocate_artifact_path,
        register_existing_artifact=register_existing_artifact,
    ))
    service._now = lambda: datetime(2026, 11, 5, 14, 23, 9)
    result = service.save_text_output(content='$ echo hello\nhello', category='command_output',
                                      client_id='client', machine_id='machine',
                                      source='pty_toolbar_action', hostname='host')
    assert result['original_name'] == 'pty_output_20261105_142309.txt'
    assert allocated[0]['artifact_type'] == 'command_output'
    assert (tmp_path / result['original_name']).read_text() == '$ echo hello\nhello'
    assert registered[0]['source_command_id'] is None
    assert registered[0]['extra']['source'] == 'pty_toolbar_action'
