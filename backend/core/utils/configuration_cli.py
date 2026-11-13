"""Shared interpretation of real set CLI flags; execution remains in ConfigurationManager."""
from core.protocol.control import ConfigurationAction

JSON_FLAGS = ('--json', 'json')
ALL_FLAGS = ('--all', 'all')
RESET_FLAGS = ('--reset', 'reset', '--unset', 'unset')
RESET_ALL_FLAGS = ('--reset-all', 'reset-all', '--unset-all', 'unset-all')


def configuration_action(parts):
    if not parts or parts[0] in JSON_FLAGS + ALL_FLAGS:
        return ConfigurationAction.GET
    if parts[0] in RESET_FLAGS + RESET_ALL_FLAGS:
        return ConfigurationAction.RESET
    return ConfigurationAction.SET


def parse_configuration_request(text, *, literal_backslashes=False):
    from core.utils.parsing import split_shell_arguments
    parts = split_shell_arguments(str(text or ''), literal_backslashes=literal_backslashes)
    output_format = 'text'
    if parts and (parts == ['json'] or (parts[-1] == '--json' and
                      (len(parts) != 2 or parts[0].startswith('--')))):
        output_format = 'json'
        parts = parts[:-1]
    action = configuration_action(parts)
    if action == ConfigurationAction.GET:
        if len(parts) > 1 or (parts and parts[0] not in ALL_FLAGS):
            raise ValueError('Usage: set [--json | --all [--json]]')
        return action, ({'include_hidden': True} if parts else {}), output_format
    if action == ConfigurationAction.RESET:
        if parts[0] in RESET_ALL_FLAGS:
            if len(parts) != 1:
                raise ValueError('Usage: set --reset-all [--json]')
            return action, {'all': True}, output_format
        if len(parts) != 2:
            raise ValueError('Usage: set --reset KEY [--json]')
        return action, {'key': parts[1]}, output_format
    if len(parts) < 2 or parts[0].startswith('--'):
        raise ValueError('Usage: set KEY value [--json]')
    return action, {'key': parts[0], 'value': ' '.join(parts[1:]), 'value_format': 'text'}, output_format


def configuration_cli_items(result):
    """Five user-facing fields derived from the full Configuration GET data."""
    return [{'key': item['key'], 'group': item['group'], 'value': item['value'],
             'override': item['source'] == 'override', 'default_value': item['default_value']}
            for item in result['items']]
