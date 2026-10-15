import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from client.commands.runtime.command_variable_resolver import (
    CommandVariableResolutionError,
    CommandVariableResolver,
)
from client.commands.strategies.python_execution.subprocess_pipe import SubprocessPipePythonExecutionStrategy
from client.runtime.sdk import variables
from client.runtime.sdk.context import build_script_sdk_globals, use_script_sdk_context


class ScriptSdkVariableTests(unittest.TestCase):
    def test_get_and_expand_inproc_reuses_runtime_resolver(self):
        resolver = CommandVariableResolver(SimpleNamespace(client_id='client-one'))
        runtime = SimpleNamespace(command_variable_resolver=resolver)
        owner = SimpleNamespace(_command_runtime=runtime)
        with use_script_sdk_context(owner, {'__context__': {'command_id': 87, 'client_id': 'client-one'}}):
            self.assertEqual('client-one', variables.get('rch:client_id'))
            self.assertEqual('87', variables.get('rch:command_id'))
            self.assertEqual('client-one at 87', variables.expand('${rch:client_id} at ${rch:command_id}'))
            with patch.dict(os.environ, {'RCH_SDK_VAR_TEST': 'works'}):
                self.assertEqual('works', variables.get('env:RCH_SDK_VAR_TEST'))
            self.assertEqual(variables.get('rch:runtime'), resolver.resolve('${rch:runtime}'))

    def test_error_cases(self):
        with use_script_sdk_context(None, {'__context__': {'client_id': 'client-one'}}):
            with self.assertRaises(ValueError):
                variables.get('launch_command')
            with self.assertRaises(CommandVariableResolutionError):
                variables.get('rch:not_a_variable')
            with self.assertRaises(CommandVariableResolutionError):
                variables.get('env:THIS_ENV_SHOULD_NOT_EXIST_9AADD1')
            with self.assertRaises(CommandVariableResolutionError):
                variables.expand('${unknown:example}')

    def test_module_is_available_in_script_globals(self):
        self.assertIs(variables, build_script_sdk_globals()['variables'])

    def test_subprocess_values_match_parent_client_not_child(self):
        backend = Path(__file__).resolve().parents[1]
        entrypoint = '/srv/rch client/rchclient.py'
        kwargs = {'__context__': {'client_id': 'client-xyz', 'command_id': 912}}
        script = '''\nimport json\nprint(json.dumps({\n    'launch_command': variables.get('rch:launch_command'),\n    'runtime': variables.get('rch:runtime'),\n    'exec_path': variables.get('rch:exec_path'),\n    'pid': variables.get('rch:pid'),\n    'client_id': variables.get('rch:client_id'),\n    'command_id': variables.get('rch:command_id'),\n}))\n'''
        strategy = SubprocessPipePythonExecutionStrategy(SimpleNamespace())
        with patch.object(sys, 'argv', [entrypoint, '--demo']):
            parent_resolver = CommandVariableResolver(SimpleNamespace(client_id='client-xyz'))
            expected = {
                name: parent_resolver.resolve('${rch:' + name + '}', command_id=912)
                for name in ('launch_command', 'runtime', 'exec_path', 'pid', 'client_id', 'command_id')
            }
            bootstrap = strategy._build_bootstrap_script(script, kwargs=kwargs)

        finished = subprocess.run(
            [sys.executable, '-u', '-'], input=bootstrap, text=True,
            capture_output=True, cwd=backend, timeout=15,
        )
        self.assertEqual(0, finished.returncode, finished.stderr)
        self.assertEqual(expected, json.loads(finished.stdout.strip()))

    def test_subprocess_nested_scripts_keep_client_values(self):
        ctx = {'__context__': {'client_id': 'client-xyz', '__rch_variables__': {
            'launch_command': 'python /opt/rchclient.py',
            'runtime': '/opt',
            'pid': '123',
        }}}
        with use_script_sdk_context(None, ctx):
            self.assertEqual('python /opt/rchclient.py', variables.get('rch:launch_command'))
            self.assertEqual('/opt', variables.get('rch:runtime'))
            self.assertEqual('123', variables.get('rch:pid'))


if __name__ == '__main__':
    unittest.main()
