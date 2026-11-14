"""Shared configuration operations for Control and the real set command."""
from client.config.runtime_config_service import RuntimeConfigService
from client.config.runtime_config_effects import RuntimeConfigEffects
from client.runtime.launch_context import is_launchd_managed_client
from core.protocol.control import ConfigurationAction
from core.protocol.configuration_result import build_configuration_result
from core.utils.runtime_config_utils import format_runtime_config_value as value_text
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


class ConfigurationManager:
    def __init__(self, connection, features=None):
        self.connection = connection
        self.service = RuntimeConfigService(features=features)

    def effects(self, key, value, checkpoint=lambda: None, launch_check=is_launchd_managed_client):
        return RuntimeConfigEffects(self.connection, launch_check, checkpoint).apply(key, value)

    def update(self, key, value, checkpoint=lambda: None, launch_check=is_launchd_managed_client, *, typed=False):
        result = self.service.set_config_value(key, value, typed=typed)
        checkpoint()
        effects = self.effects(result.key, result.new_value, checkpoint, launch_check)
        checkpoint()
        return result, effects

    def reset(self, key, checkpoint=lambda: None, launch_check=is_launchd_managed_client):
        result = self.service.reset_config_key(key)
        return result, self.effects(result.key, result.new_value, checkpoint, launch_check)

    def reset_all(self, checkpoint=lambda: None, launch_check=is_launchd_managed_client):
        path = self.service.reset_all_overrides()
        messages = []
        for key, value, _, _ in self.service.list_config_items(include_hidden=True):
            messages.extend(self.effects(key, value, checkpoint, launch_check))
        return path, messages

    def execute(self, scope, action, payload):
        try:
            if action == ConfigurationAction.GET:
                return 1, build_configuration_result(
                    action, data=self.service.build_config_payload(
                        include_hidden=payload.get('include_hidden', False) is True))
            if action == ConfigurationAction.SET:
                if 'value' not in payload or isinstance(payload['value'], (dict, list)):
                    raise ValueError('A scalar config value is required')
                value_format = payload.get('value_format', 'typed')
                if value_format not in ('typed', 'text') or (value_format == 'text' and not isinstance(payload['value'], str)):
                    raise ValueError('Invalid configuration value format')
                change, messages = self.update(payload.get('key'), payload['value'], scope._checkpoint, typed=value_format == 'typed')
            elif action == ConfigurationAction.RESET:
                if payload.get('all') is True:
                    if payload.get('key'):
                        raise ValueError('Specify a key or reset all')
                    _, messages = self.reset_all(scope._checkpoint)
                    change = None
                else:
                    change, messages = self.reset(payload.get('key'), scope._checkpoint)
            else:
                return 0, 'Unsupported configuration Control action'
            for message in messages:
                scope._send_interim_result(1, message)
            if change is None:
                message = 'All runtime config overrides reset to defaults.'
            elif action == ConfigurationAction.SET:
                message = (f'{change.key} updated: {value_text(change.old_value)} '
                           f'→ {value_text(change.new_value)}')
            else:
                message = f'{change.key} reset to default: {value_text(change.new_value)}'
            return 1, build_configuration_result(action, message=message)
        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as exc:
            return 0, build_configuration_result(action, status='error', message=(str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)))
