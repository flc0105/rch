"""Server-only Configuration CLI, sharing the Web Configuration Control."""
from core.protocol.control import ControlDomain, ConfigurationAction, WatchdogAction, execution_policy, ExecutionPolicy
from core.protocol.result_envelope import ResultEvent
from core.protocol.result_envelope import ResultEnvelope
from core.utils.configuration_cli import configuration_cli_items
from core.utils.command_output import (OutputFormat, ResultDataShape, render_result_payload, resolve_presentation)
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
        output_format, layout = (resolve_presentation(args, ResultDataShape.GROUPED)
                                 if invocation.action == 'list' else (invocation.output_format, None))
        for item in self._send(ControlDomain.CONFIGURATION, action, payload):
            result = item.event
            if item.terminal_status is None:
                if output_format != 'json':
                    yield item.with_text(str(result.get('message') or ''))
                continue
            displayed = result
            if item.succeeded and action == ConfigurationAction.GET:
                try:
                    displayed = {**result, 'data': configuration_cli_items(result['data'])}
                except (KeyError, ValueError, TypeError) as exc:
                    item = ResultEvent.completed('error', str(exc) or 'Invalid Configuration response')
                    displayed = item.event
            text = render_result_payload(displayed, output_format,
                                         view='data' if action == ConfigurationAction.GET and item.succeeded else 'message',
                                         shape=layout or ResultDataShape.TABLE, line_field=('group', 'key'),
                                         line_separator='.', group_field='group', key_field='key', value_field='value')
            yield item.with_text(text)

    def watchdog(self, invocation):
        for item in self._send(ControlDomain.WATCHDOG, WatchdogAction.STATUS, {}):
            result = item.event
            if item.terminal_status is None:
                if invocation.output_format != OutputFormat.JSON:
                    yield item.with_text(str(result.get('message') or ''))
                continue
            if item.succeeded and not isinstance(result.get('data'), dict):
                item = ResultEvent.completed('error', result.get('message') or 'Watchdog status unavailable')
            if not item.succeeded:
                yield item.with_text(render_result_payload(item.event, invocation.output_format))
                continue
            output, layout = resolve_presentation(invocation.arguments, ResultDataShape.GROUPED)
            yield item.with_text(render_result_payload(item.event, output, view='data', shape=layout))
