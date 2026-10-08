import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from client.commands.runtime.command_variable_resolver import CommandVariableResolver
from client.runtime.client_util import get_runtime_root


class CommandVariableRuntimeTests(unittest.TestCase):
    def test_runtime_root_uses_source_entrypoint_directory(self):
        entrypoint = os.path.join(os.sep, 'opt', 'rch client', 'rchclient.py')
        with patch.object(sys, 'argv', [entrypoint]):
            self.assertEqual(
                os.path.dirname(os.path.realpath(entrypoint)),
                get_runtime_root(),
            )

    def test_runtime_root_uses_frozen_executable_directory(self):
        executable = os.path.join(os.sep, 'Applications', 'RCH', 'rchclient')
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', executable):
            self.assertEqual(
                os.path.dirname(os.path.realpath(executable)),
                get_runtime_root(),
            )

    def test_rch_runtime_variable_and_manifest(self):
        entrypoint = os.path.join(os.sep, 'srv', 'rch', 'rchclient.py')
        resolver = CommandVariableResolver(SimpleNamespace(client_id='client-1'))

        with patch.object(sys, 'argv', [entrypoint]):
            self.assertEqual(
                os.path.dirname(os.path.realpath(entrypoint)),
                resolver.resolve('${rch:runtime}'),
            )

        item = next(
            entry
            for entry in resolver.get_manifest_payload()
            if entry.get('namespace') == 'rch' and entry.get('name') == 'runtime'
        )
        self.assertEqual('${rch:runtime}', item['template'])
        self.assertIn('runtime root', item['description'].lower())


if __name__ == '__main__':
    unittest.main()
