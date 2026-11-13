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
    action = configuration_action(parts)
    if action == ConfigurationAction.GET:
        if len(parts) > 1:
            raise ValueError('Usage: set [--json | --all]')
        return action, ({'include_hidden': True} if parts and parts[0] in ALL_FLAGS else {}), ('json' if parts and parts[0] in JSON_FLAGS else 'text')
    if action == ConfigurationAction.RESET:
        if parts[0] in RESET_ALL_FLAGS:
            if len(parts) != 1:
                raise ValueError('Usage: set --reset-all')
            return action, {'all': True}, 'text'
        if len(parts) != 2:
            raise ValueError('Usage: set --reset KEY')
        return action, {'key': parts[1]}, 'text'
    if len(parts) < 2 or parts[0].startswith('--'):
        raise ValueError('Usage: set KEY value')
    return action, {'key': parts[0], 'value': ' '.join(parts[1:]), 'value_format': 'text'}, 'text'
