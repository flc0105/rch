"""Server command entry points for runtime configuration and Watchdog."""
import json

from core.protocol.control import ControlDomain, ConfigurationAction, WatchdogAction, execution_policy, ExecutionPolicy
from core.protocol.message_queue import ResultChunk
from core.utils.configuration_cli import parse_configuration_request
from core.utils.command_output import StructuredCommandResult, parse_output_format, render_structured_result
from core.utils.runtime_config_utils import format_runtime_config_value as value_text
from core.utils.output_marker import success, info, warning, error
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
                          payload=payload, extra={'timeout': 30} if domain == ControlDomain.CONFIGURATION else None, history_entry_id=self.history_entry_id_provider() or '')

    def set(self, arg=''):
        platform = getattr(self.conn.session_info, 'os_alias', '')
        try:
            action, payload, output_format = parse_configuration_request(arg, literal_backslashes=platform == 'windows' or platform == 'win')
        except ValueError as exc:
            yield 0, error(str(exc))
            return
        for item in self._send(ControlDomain.CONFIGURATION, action, payload):
            status, result = item[:2]
            if not getattr(item, 'eof', True) or status != 1 or not isinstance(result, dict):
                yield item
                continue
            if action == ConfigurationAction.GET:
                message = json.dumps(result, ensure_ascii=False) if output_format == 'json' else format_listing(result)
            elif action == ConfigurationAction.RESET and payload.get('all'):
                message = success('All runtime config overrides reset to runtime_config.py defaults\n') + info('Runtime config store: ' + result['store_path'])
            else:
                change = result['change']
                key, old, new = change['key'], value_text(change['old_value']), value_text(change['new_value'])
                message = (success(f'{key} updated, value: {old} → {new}') if action == ConfigurationAction.SET
                           else success(f'{key} reset to default: ') + f'{old} -> {new}')
            yield ResultChunk(status, message, getattr(item, 'eof', True), terminal_authoritative=True)

    def watchdog(self, arg=''):
        for item in self._send(ControlDomain.WATCHDOG, WatchdogAction.STATUS, {}):
            status, result = item[:2]
            if status != 1 or not getattr(item, 'eof', True) or not isinstance(result, dict):
                yield item
                continue
            _, text = render_structured_result(StructuredCommandResult(1, result, shape='grouped_dict'), parse_output_format(arg))
            yield ResultChunk(status, text, getattr(item, 'eof', True), terminal_authoritative=True)


def format_listing(result):
    items = result['items']
    lines = [info('Runtime config store path: ' + result['store_path'])]
    overrides = sorted((item for item in items if item['source'] == 'override'), key=lambda item: item['key'])
    lines.append(warning('Active overrides:' if overrides else 'Active overrides: none'))
    for item in overrides:
        lines.append(f"  {item['key']} = {value_text(item['value'])} (default={value_text(item['default_value'])})")
    if result.get('pruned'):
        lines.append(warning('Pruned redundant overrides: ') + ', '.join(result['pruned']))
    for group in sorted({item['group'] for item in items}):
        lines.extend(['', f'[{group}]'])
        for item in items:
            if item['group'] == group:
                source = ('override, default=' + value_text(item['default_value']) if item['source'] == 'override' else 'default')
                lines.append(f"{item['key']} = {value_text(item['value'])}  [{source}]")
    if not items:
        lines.append(error('No runtime config items'))
    return '\n'.join(lines)
