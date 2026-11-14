"""Server-only Configuration CLI, sharing the Web Configuration Control."""
from core.protocol.control import ControlDomain, ConfigurationAction, WatchdogAction, execution_policy, ExecutionPolicy
from core.protocol.message_queue import ResultChunk
from core.protocol.result_envelope import ResultEnvelope
from core.utils.configuration_cli import configuration_cli_items
from core.utils.command_output import (ResultDisplay, StructuredCommandResult,
                                       parse_output_format, render_result_payload, render_structured_result)
from server.application.command.command_types import COMMAND_TYPE_CONTROL


class ConfigurationBuiltinSupport:
    def __init__(self, conn, remote_execution_service, history_entry_id_provider, use_foreground_guard=False):
        self.conn = conn
        self.remote_execution_service = remote_execution_service
        self.history_entry_id_provider = history_entry_id_provider
        self.use_foreground_guard = use_foreground_guard

    def _send(self, domain, action, payload):
        foreground = self.use_foreground_guard and execution_policy(domain, action) == ExecutionPolicy.FOREGROUND
        stream = (self.remote_execution_service.stream_foreground_command if foreground
                  else self.remote_execution_service.stream_command)
        yield from stream(self.conn, '', command_type=COMMAND_TYPE_CONTROL, domain=domain, action=action,
                          payload=payload, extra={'timeout': 30} if domain == ControlDomain.CONFIGURATION else None,
                          history_entry_id=self.history_entry_id_provider() or '')

    def config(self, invocation):
        action = {
            'list': ConfigurationAction.GET, 'set': ConfigurationAction.SET,
            'reset': ConfigurationAction.RESET, 'reset-all': ConfigurationAction.RESET,
        }[invocation.action]
        args = invocation.arguments
        payload = {}
        if action == ConfigurationAction.SET:
            payload = {'key': args['key'], 'value': args['value'], 'value_format': 'text'}
        elif invocation.action == 'reset':
            payload = {'key': args['key']}
        elif invocation.action == 'reset-all':
            payload = {'all': True}
        output_format = invocation.output_format
        for item in self._send(ControlDomain.CONFIGURATION, action, payload):
            status, result = item[:2]
            if not getattr(item, 'eof', True):
                if output_format != 'json':
                    yield item
                continue
            if not isinstance(result, dict) or result.get('display') not in (ResultDisplay.MESSAGE, ResultDisplay.DATA):
                result = ResultEnvelope(status='error', message=(
                    str(result) if status != 1 else 'Invalid Configuration response')).as_payload()
                status = 0
            if status == 1 and action == ConfigurationAction.GET:
                result = {**result, 'data': configuration_cli_items(result['data']), 'shape': 'table'}
            yield ResultChunk(status, render_result_payload(result, output_format),
                              getattr(item, 'eof', True), terminal_authoritative=True)

    def watchdog(self, arg=''):
        for item in self._send(ControlDomain.WATCHDOG, WatchdogAction.STATUS, {}):
            status, result = item[:2]
            if status != 1 or not getattr(item, 'eof', True) or not isinstance(result, dict):
                yield item
                continue
            _, text = render_structured_result(StructuredCommandResult(1, result, shape='grouped_dict'), parse_output_format(arg))
            yield ResultChunk(status, text, getattr(item, 'eof', True), terminal_authoritative=True)
