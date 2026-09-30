import os
import tempfile
import unittest
from unittest.mock import patch

from server.application.agent.agent_builder import AgentBuilder
from server.application.maintenance.server_cleanup_service import ServerCleanupService


class AgentBuilderTests(unittest.TestCase):
    def _builder_for(self, source_dir: str, output_dir: str) -> AgentBuilder:
        builder = AgentBuilder.__new__(AgentBuilder)
        builder.source_dir = source_dir
        builder.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        return builder

    def test_pyinstaller_staging_uses_allowlist(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as temp_dir:
            for relative_path in ('client', 'core', 'server', 'runtime'):
                os.makedirs(os.path.join(source_dir, relative_path), exist_ok=True)
            with open(os.path.join(source_dir, 'client', 'client.py'), 'w', encoding='utf-8') as fp:
                fp.write('client')
            with open(os.path.join(source_dir, 'core', 'core.py'), 'w', encoding='utf-8') as fp:
                fp.write('core')
            with open(os.path.join(source_dir, 'rchclient.py'), 'w', encoding='utf-8') as fp:
                fp.write('entry')
            with open(os.path.join(source_dir, 'server', 'secret.py'), 'w', encoding='utf-8') as fp:
                fp.write('server')
            with open(os.path.join(source_dir, 'runtime', 'state.bin'), 'w', encoding='utf-8') as fp:
                fp.write('runtime')
            with open(os.path.join(source_dir, 'nohup.out'), 'w', encoding='utf-8') as fp:
                fp.write('log')

            builder = self._builder_for(source_dir, os.path.join(temp_dir, 'output'))
            staging_dir = os.path.join(temp_dir, 'staging')
            builder._copy_source_paths(builder.PYINSTALLER_INCLUDE_PATHS, staging_dir)

            self.assertTrue(os.path.isfile(os.path.join(staging_dir, 'client', 'client.py')))
            self.assertTrue(os.path.isfile(os.path.join(staging_dir, 'core', 'core.py')))
            self.assertTrue(os.path.isfile(os.path.join(staging_dir, 'rchclient.py')))
            self.assertFalse(os.path.exists(os.path.join(staging_dir, 'server')))
            self.assertFalse(os.path.exists(os.path.join(staging_dir, 'runtime')))
            self.assertFalse(os.path.exists(os.path.join(staging_dir, 'nohup.out')))

    def test_build_workspace_is_removed_after_success(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, 'output')
            work_dir = os.path.join(temp_dir, 'agent_build_success')
            os.makedirs(work_dir)
            builder = self._builder_for(source_dir, output_dir)

            def fake_bundle(**kwargs):
                artifact = os.path.join(kwargs['work_dir'], 'agent.zip')
                with open(artifact, 'wb') as fp:
                    fp.write(b'agent')
                return {
                    'file_path': artifact,
                    'file_name': 'agent.zip',
                    'warnings': [],
                    'target_arch': 'n/a',
                    'target_os': 'bundle',
                }

            with patch('server.application.agent.agent_builder.tempfile.mkdtemp', return_value=work_dir), \
                    patch.object(builder, '_build_with_bundle', side_effect=fake_bundle):
                result = builder.build_agent(
                    server_host='127.0.0.1',
                    server_port=9000,
                    web_port=8080,
                    file_transfer_port=8081,
                    builder='bundle',
                )

            self.assertFalse(os.path.exists(work_dir))
            self.assertTrue(os.path.isfile(result['file_path']))
            self.assertNotIn('work_dir', result)

    def test_build_workspace_is_removed_after_failure(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, 'output')
            work_dir = os.path.join(temp_dir, 'agent_build_failure')
            os.makedirs(work_dir)
            builder = self._builder_for(source_dir, output_dir)

            with patch('server.application.agent.agent_builder.tempfile.mkdtemp', return_value=work_dir), \
                    patch.object(builder, '_build_with_bundle', side_effect=RuntimeError('build failed')):
                with self.assertRaisesRegex(RuntimeError, 'build failed'):
                    builder.build_agent(
                        server_host='127.0.0.1',
                        server_port=9000,
                        web_port=8080,
                        file_transfer_port=8081,
                        builder='bundle',
                    )

            self.assertFalse(os.path.exists(work_dir))

    def test_startup_cleanup_finds_abandoned_agent_workspaces(self):
        service = ServerCleanupService.__new__(ServerCleanupService)
        with tempfile.TemporaryDirectory() as temp_root:
            owned = os.path.join(temp_root, 'agent_build_abandoned')
            unrelated = os.path.join(temp_root, 'other_temp')
            os.makedirs(owned)
            os.makedirs(unrelated)

            with patch('server.application.maintenance.server_cleanup_service.tempfile.gettempdir', return_value=temp_root):
                work_dirs = service._snapshot_agent_build_temp()

            self.assertEqual(work_dirs, [owned])


if __name__ == '__main__':
    unittest.main()
