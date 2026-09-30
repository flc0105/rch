import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from client.external_tools.launcher import apply_external_tool_launcher
from client.external_tools.oneshot import ExternalToolOneshot
from core.external_tools.paths import (
    EXTERNAL_TOOLS_INSTALL_ROOT,
    EXTERNAL_TOOLS_PACKAGE_CACHE_ROOT,
    EXTERNAL_TOOLS_RUNTIME_ROOT,
    external_tool_instance_runtime_parts,
    external_tool_instances_runtime_parts,
    external_tool_oneshot_runtime_parts,
    sanitize_instance_id,
)
from server.application.external_tools.external_tool_context_runtime import ExternalToolContextRuntime


class ExternalToolRuntimeTests(unittest.TestCase):
    def test_direct_launcher_preserves_existing_argv(self):
        argv = ['/opt/tool/bin/tool', '--port', '9000']
        self.assertEqual(apply_external_tool_launcher(argv, None), argv)

    def test_client_python_launcher_keeps_prefix_and_entrypoint(self):
        with patch('client.external_tools.launcher._resolve_client_python_command', return_value=['/client/python']):
            argv = apply_external_tool_launcher(
                ['/bundle/app.py', '--port', '9000'],
                {'type': 'client_python', 'prefix_args': ['-u']},
            )
        self.assertEqual(argv, ['/client/python', '-u', '/bundle/app.py', '--port', '9000'])

    def test_oneshot_applies_launcher_explicitly(self):
        tool = ExternalToolOneshot.__new__(ExternalToolOneshot)
        with tempfile.TemporaryDirectory() as cwd, \
                patch('client.external_tools.launcher._resolve_client_python_command', return_value=['/client/python']), \
                patch('client.external_tools.oneshot.run_foreground_process') as run_process:
            run_process.return_value = {
                'returncode': 0,
                'stdout': '',
                'stderr': '',
                'timed_out': False,
            }
            result = tool.run_foreground(
                {'cwd': cwd, 'argv': ['app.py', '--check']},
                launcher={'type': 'client_python', 'prefix_args': ['-u']},
            )

        argv = run_process.call_args.args[0]['argv']
        self.assertEqual(argv, ['/client/python', '-u', os.path.abspath('app.py'), '--check'])
        self.assertEqual(result['argv'], argv)

    def test_runtime_roots_have_one_shared_definition(self):
        self.assertEqual(EXTERNAL_TOOLS_INSTALL_ROOT, '~/.ops/external_tools/installed')
        self.assertEqual(EXTERNAL_TOOLS_RUNTIME_ROOT, '~/.ops/external_tools/runtime')
        self.assertEqual(EXTERNAL_TOOLS_PACKAGE_CACHE_ROOT, '~/.ops/external_tools/packages')
        self.assertEqual(
            external_tool_instance_runtime_parts('pkg', 'mod', 'demo name'),
            ('pkg', 'mod', 'instances', 'demo-name'),
        )
        self.assertEqual(
            external_tool_instances_runtime_parts('pkg', 'mod'),
            ('pkg', 'mod', 'instances'),
        )
        self.assertEqual(
            external_tool_oneshot_runtime_parts('pkg', 'mod', 'run id'),
            ('pkg', 'mod', 'oneshot', 'run-id'),
        )

    def test_server_is_single_source_for_derived_instance_id(self):
        core = SimpleNamespace(_sanitize_instance_id=sanitize_instance_id)
        runtime = ExternalToolContextRuntime(core)
        meta = {'id': 'server', 'name': 'frps'}

        self.assertEqual(runtime._derive_instance_id(meta, {'bind_port': 7000}), 'frps-7000')
        self.assertEqual(
            runtime._derive_instance_id(meta, {'proxy_name': 'vite', 'remote_port': 8087}),
            'vite-8087',
        )
        self.assertEqual(runtime._derive_instance_id(meta, {}, explicit='custom instance'), 'custom-instance')


if __name__ == '__main__':
    unittest.main()
