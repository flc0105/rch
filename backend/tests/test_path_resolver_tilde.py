import os
import tempfile
import unittest
from unittest.mock import patch

from client.commands.common.services.filesystem.path_resolver import PathResolver
from client.external_tools.daemon_instance import ExternalToolDaemonInstance


class PathResolverTildeTests(unittest.TestCase):
    def test_resolve_target_path_expands_remote_home(self):
        resolver = PathResolver()
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            expected = os.path.join(home, 'Documents', 'Typora')
            self.assertEqual(
                resolver.resolve_target_path('~/Documents/Typora'),
                os.path.abspath(expected),
            )

    def test_existing_directory_helpers_accept_tilde_paths(self):
        resolver = PathResolver()
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            target = os.path.join(home, 'Documents', 'Typora')
            os.makedirs(target)

            self.assertEqual(
                resolver.require_existing_directory_from_arg('~/Documents/Typora'),
                os.path.abspath(target),
            )
            self.assertEqual(
                resolver.validate_directory_exists('~/Documents/Typora'),
                os.path.abspath(target),
            )

    def test_external_tool_runtime_expands_tilde_argv_on_client(self):
        tool = ExternalToolDaemonInstance.__new__(ExternalToolDaemonInstance)
        tool.validate_package_payload = lambda payload, action='': ('mac', 'arm64')

        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            runtime = tool.build_runtime({
                'runtime': {
                    'argv': [
                        '/usr/bin/env',
                        'SB_USER=admin:admin',
                        '/tmp/silverbullet',
                        '--single',
                        '~/Documents/Typora',
                    ],
                    'cwd': home,
                    'stdout': os.path.join(home, 'stdout.log'),
                    'pid_file': os.path.join(home, 'tool.pid'),
                },
            })

        self.assertEqual(
            runtime['argv'][-1],
            os.path.abspath(os.path.join(home, 'Documents', 'Typora')),
        )

    def test_relative_paths_keep_current_working_directory_semantics(self):
        resolver = PathResolver()
        with tempfile.TemporaryDirectory() as cwd, patch('os.getcwd', return_value=cwd):
            self.assertEqual(
                resolver.resolve_target_path('Documents/Typora'),
                os.path.abspath(os.path.join(cwd, 'Documents', 'Typora')),
            )


if __name__ == '__main__':
    unittest.main()
