"""Server-only Configuration CLI, sharing the Web Configuration Control."""
from core.protocol.control import ControlDomain, ConfigurationAction, WatchdogAction, execution_policy, ExecutionPolicy
from core.protocol.message_queue import ResultChunk
from core.protocol.result_envelope import ResultEnvelope
from core.utils.configuration_cli import configuration_cli_items
from core.utils.command_output import (OutputFormat, ResultDataShape, render_result_payload)
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
            final = getattr(item, 'eof', True)
            if not final:
                if output_format != 'json':
                    yield ResultChunk(status, str(result.get('message') or '') if isinstance(result, dict) else str(result), False,
                                      terminal_authoritative=True, event=getattr(item, 'event', None))
                continue
            if not isinstance(result, dict) or result.get('event_type') != 'completed':
                result = ResultEnvelope(status='error', message=(
                    str(result) if status != 1 else 'Invalid Configuration response')).as_payload()
                status = 0
            if status == 1 and action == ConfigurationAction.GET:
                result = {**result, 'data': configuration_cli_items(result['data'])}
            text = render_result_payload(result, output_format,
                                         view='data' if action == ConfigurationAction.GET and status == 1 else 'message',
                                         shape=ResultDataShape.TABLE)
            yield ResultChunk(status, text, True, terminal_authoritative=True,
                              event=getattr(item, 'event', None))

    def watchdog(self, invocation):
        for item in self._send(ControlDomain.WATCHDOG, WatchdogAction.STATUS, {}):
            status, result = item[:2]
            final = getattr(item, 'eof', True)
            if not final:
                if invocation.output_format != OutputFormat.JSON:
                    yield ResultChunk(status, str(result.get('message') or '') if isinstance(result, dict) else str(result), False,
                                      terminal_authoritative=True, event=getattr(item, 'event', None))
                continue
            if status != 1 or not isinstance(result, dict) or not isinstance(result.get('data'), dict):
                message = (result.get('message') if isinstance(result, dict) else str(result))
                envelope = ResultEnvelope(status='error', message=message or 'Watchdog status unavailable').as_payload()
                text = render_result_payload(envelope, invocation.output_format)
                yield ResultChunk(0, text, True, terminal_authoritative=True, event=getattr(item, 'event', None))
                continue
            text = render_result_payload(result, invocation.output_format,
                                         view='data', shape=ResultDataShape.GROUPED)
            yield ResultChunk(status, text, True, terminal_authoritative=True, event=getattr(item, 'event', None))
