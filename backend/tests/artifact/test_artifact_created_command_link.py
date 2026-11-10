import unittest
from types import SimpleNamespace

from server.application.web.artifact_api import WebArtifactApi


class ArtifactEventSourceTests(unittest.TestCase):
    def test_publisher_forwards_exact_command_id_and_keeps_existing_event_fields(self):
        events = []
        bus = SimpleNamespace(publish=lambda event, payload: events.append((event, payload)))
        api = WebArtifactApi(None, bus, None)
        api.publish_artifact_created({
            'artifact_id': 'artifact-123', 'client_id': 'client-1',
            'source_command_id': 42, 'original_name': 'chart.png',
            'download_url': '/api/artifacts/artifact-123/download',
        })
        self.assertEqual(len(events), 1)
        name, payload = events[0]
        self.assertEqual(name, 'artifact_created')
        self.assertEqual(payload['source_command_id'], 42)
        self.assertEqual(payload['client_id'], 'client-1')
        self.assertEqual(payload['original_name'], 'chart.png')
        self.assertEqual(payload['download_url'], '/api/artifacts/artifact-123/download')
        api.publish_artifact_created({'artifact_id': 'remote-only'})
        self.assertIsNone(events[-1][1]['source_command_id'])


if __name__ == '__main__':
    unittest.main()
