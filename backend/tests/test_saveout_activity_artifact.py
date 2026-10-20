"""saveout links an already registered artifact to the dispatched Activity."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from server.application.command.command_output_builtin_support import CommandOutputBuiltinSupport


class SaveoutActivityArtifactTests(unittest.TestCase):
    def test_registered_saveout_artifact_is_added_once_to_activity(self):
        with tempfile.TemporaryDirectory() as folder:
            filepath = os.path.join(folder, 'output.txt')
            artifact = {'artifact_id': 'artifact-1', 'original_name': 'output.txt', 'size': 8}
            store = SimpleNamespace(append_file_for_connection=Mock())
            server = SimpleNamespace(command_history_orchestrator=SimpleNamespace(history_store=store))
            conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='m1', client_id='c1', hostname='host'),
                                   get_foreground_task=lambda: {})
            support = CommandOutputBuiltinSupport(server, conn, None, None,
                                                  history_entry_id_provider=lambda: 'activity-1')
            support._allocate_output_artifact = lambda **kw: {
                'file_path': filepath, 'machine_id': 'm1', 'original_name': 'output.txt',
            }
            support._register_output_artifact = lambda **kw: artifact
            support._build_inner_executor = lambda command: (lambda: iter([(1, 'output')]))
            result = list(support.saveout('shell echo hello'))
            self.assertEqual(1, result[-1][0])
            store.append_file_for_connection.assert_called_once_with(conn, 'activity-1', artifact)
            with open(filepath) as f:
                self.assertIn('output', f.read())

    def test_no_activity_does_not_create_artifact_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SimpleNamespace(append_file_for_connection=Mock())
            server = SimpleNamespace(command_history_orchestrator=SimpleNamespace(history_store=store))
            conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='m1', client_id='c1'),
                                   get_foreground_task=lambda: {})
            support = CommandOutputBuiltinSupport(server, conn, None, None, lambda: '')
            support._allocate_output_artifact = lambda **kw: {'file_path': os.path.join(folder,'o.txt')}
            support._register_output_artifact = lambda **kw: {'artifact_id': 'artifact-1'}
            support._build_inner_executor = lambda command: (lambda: iter([(1,'ok')]))
            self.assertEqual(1, list(support.saveout('echo ok'))[-1][0])
            store.append_file_for_connection.assert_not_called()


if __name__ == '__main__':
    unittest.main()
