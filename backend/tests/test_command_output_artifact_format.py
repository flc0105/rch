import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from server.application.artifact.command_output_artifact_service import CommandOutputArtifactService


class FakeArtifactService:
    def __init__(self, root):
        self.root = Path(root)

    def allocate_artifact_path(self, *, artifact_type, machine_id, original_name, category=''):
        directory = self.root / category / machine_id
        directory.mkdir(parents=True, exist_ok=True)
        file_path = directory / original_name
        return {
            'artifact_type': artifact_type,
            'category': category,
            'machine_id': machine_id,
            'original_name': original_name,
            'stored_name': original_name,
            'file_path': str(file_path),
            'meta_path': str(file_path) + '.meta.json',
        }

    def register_existing_artifact(self, **payload):
        return payload


class CommandOutputArtifactFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = FakeArtifactService(self.temp.name)
        self.service = CommandOutputArtifactService(self.registry)
        self.fixed_now = datetime(2026, 10, 27, 9, 0, 0)

    def test_output_names_select_txt_or_json_without_changing_default(self):
        self.assertEqual(
            self.service.build_output_name(category='command_output', source_command='', now=self.fixed_now),
            'cmd_20261027_090000_output.txt',
        )
        self.assertEqual(
            self.service.build_output_name(category='command_output', source_command='', now=self.fixed_now, output_format='json'),
            'cmd_20261027_090000_output.json',
        )
        self.assertEqual(
            self.service.build_output_name(category='job_output', source_command='report', now=self.fixed_now),
            'job_output_20261027_090000_report.json',
        )

    def test_json_output_is_saved_as_valid_json_artifact(self):
        content = json.dumps([{'command': 'pwd', 'result': '/home/demo'}])
        self.service._now = lambda: self.fixed_now
        artifact = self.service.save_text_output(
            content=content,
            category='command_output',
            hostname='demo-host',
            machine_id='machine-1',
            source='terminal_toolbar_action',
            output_format='json',
        )
        path = Path(artifact['file_path'])
        self.assertEqual(path.suffix, '.json')
        self.assertEqual(artifact['original_name'], 'terminal_output_20261027_090000.json')
        self.assertEqual(path.name, 'terminal_output_20261027_090000.json')
        self.assertEqual(path.read_text(encoding='utf-8'), content)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))[0]['command'], 'pwd')

    def test_terminal_toolbar_text_export_uses_fixed_timestamp_name(self):
        self.service._now = lambda: self.fixed_now
        artifact = self.service.save_text_output(
            content='terminal output',
            category='command_output',
            hostname='demo-host',
            machine_id='machine-1',
            source='terminal_toolbar_action',
            output_format='text',
        )
        self.assertEqual(artifact['original_name'], 'terminal_output_20261027_090000.txt')
        self.assertEqual(Path(artifact['file_path']).name, 'terminal_output_20261027_090000.txt')

    def test_terminal_toolbar_saved_from_metadata_uses_fixed_timestamp_name(self):
        self.service._now = lambda: self.fixed_now
        artifact = self.service.save_text_output(
            content='terminal output',
            category='command_output',
            hostname='demo-host',
            machine_id='machine-1',
            source='terminal_export',
            extra={'saved_from': 'terminal_toolbar'},
            output_format='text',
        )
        self.assertEqual(artifact['original_name'], 'terminal_output_20261027_090000.txt')

    def test_json_format_rejects_invalid_json_and_unknown_formats(self):
        with self.assertRaisesRegex(ValueError, 'valid JSON'):
            self.service.save_text_output(
                content='not json', category='command_output', hostname='demo', machine_id='machine-1', output_format='json',
            )
        with self.assertRaisesRegex(ValueError, 'output_format must be text or json'):
            self.service.build_output_name(category='command_output', source_command='', output_format='xml')


if __name__ == '__main__':
    unittest.main()
