"""Transfer toast actions depend on actual completed Artifact-producing direction."""
import pytest

from server.application.preferences.notification_event_projector import NotificationEventProjector


@pytest.mark.parametrize('direction,state,artifact_id,expected', [
    ('client_to_server', 'completed', 'abcd', ['open_transfers', 'open_artifacts', 'artifact_download']),
    ('client_to_server', 'completed', '', ['open_transfers']),
    ('server_to_client', 'completed', 'abcd', ['open_transfers']),
    ('client_to_server', 'cancelled', 'abcd', ['open_transfers']),
    ('client_to_server', 'failed', 'abcd', ['open_transfers']),
    ('browser_to_server', 'completed', 'abcd', ['open_transfers']),
])
def test_transfer_notification_actions(direction, state, artifact_id, expected):
    projector = NotificationEventProjector(history_store=None, server=None)
    payload = {
        'lifecycle': 'error' if state == 'failed' else 'stopped', 'state': state,
        'client_id': 'client', 'filename': 'sample.txt', 'direction': direction,
        'artifact_id': artifact_id, 'transfer_id': 'trans-a',
    }
    result = projector._build_file_transfer_lifecycle(payload)
    assert [x['type'] for x in result['actions']] == expected
    if 'artifact_download' in expected:
        assert result['context']['artifact_id'] == artifact_id
        assert result['actions'][-1]['url'] == f'/api/artifacts/{artifact_id}/download'
