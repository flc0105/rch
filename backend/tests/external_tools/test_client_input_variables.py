"""External Tool input values are resolved on the target Client at execution time."""
import os
import unittest
from types import SimpleNamespace

from client.commands.common.mixins.external_tool_ops import CommandExternalToolMixin
from client.commands.runtime.command_variable_resolver import (
    CommandVariableResolutionError,
    CommandVariableResolver,
)


class _PayloadHost(CommandExternalToolMixin):
    def __init__(self, resolver):
        self._command_runtime = SimpleNamespace(command_variable_resolver=resolver)
        self.structured_arg_codec = SimpleNamespace(decode=lambda value: value)


class ExternalToolClientInputVariablesTests(unittest.TestCase):
    def setUp(self):
        resolver = CommandVariableResolver(SimpleNamespace(client_id='client-123'))
        resolver.set_var('GREETING', '你好')
        self.host = _PayloadHost(resolver)

    def test_resolve_text_input_in_argv_config_and_params(self):
        payload = {
            'params': {'output': 'report-${rch:pid}.log', 'count': 3, 'paths': ['${path:home}/logs', 'C:\\Users\\用户\\log.log']},
            'runtime': {'argv': ['tool', '--path=${env:HOME}', '--output', '{{not-a-variable}}', 'report-${rch:pid}.log'], 'timeout_sec': 1.5},
            'config': {'files': [{'output': 'report-${rch:pid}.log'}], 'enabled': False},
            'tool_id': 'sample',
        }
        result = self.host._decode_external_tool_payload(payload)
        name = f'report-{os.getpid()}.log'
        self.assertEqual(result['params']['output'], name)
        self.assertEqual(result['runtime']['argv'][-1], name)
        self.assertEqual(result['config']['files'][0]['output'], name)
        self.assertEqual(result['params']['paths'][1], 'C:\\Users\\用户\\log.log')
        self.assertEqual(result['params']['count'], 3)
        self.assertEqual(result['runtime']['timeout_sec'], 1.5)
        self.assertFalse(result['config']['enabled'])
        self.assertEqual(result['tool_id'], 'sample')

    def test_missing_and_unsupported_variable_fail_without_execution(self):
        with self.assertRaises(CommandVariableResolutionError):
            self.host._decode_external_tool_payload({'runtime': {'argv': ['tool', '${var:MISSING}']}})
        with self.assertRaises(CommandVariableResolutionError):
            self.host._decode_external_tool_payload({'params': {'path': '${unknown:path}'}})

    def test_server_rendered_external_tool_input_reaches_client_argv(self):
        from tests.external_tools.test_tool_runtime import FFmpegScreenRecordMetaTests

        fixture = FFmpegScreenRecordMetaTests
        fixture.setUpClass()
        payload = fixture().payload('mac', output_filename='capture-${rch:pid}.mp4')
        self.assertIn('${rch:pid}', payload['runtime']['argv'][-1])
        result = self.host._decode_external_tool_payload(payload)
        self.assertTrue(result['runtime']['argv'][-1].endswith(f'capture-{os.getpid()}.mp4'))
        self.assertEqual(result['params']['output_filename'], f'capture-{os.getpid()}.mp4')

    def test_payload_without_variables_is_unchanged(self):
        payload = {'params': {'name': 'test'}, 'runtime': {'argv': ['tool', 'safe']}}
        self.assertEqual(self.host._decode_external_tool_payload(payload), payload)
