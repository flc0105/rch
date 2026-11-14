"""Configuration Terminal and Web share GET facts, not presentation fields."""
import json
from types import SimpleNamespace

import pytest

from core.protocol.control import ConfigurationAction
from core.protocol.configuration_result import build_configuration_result
from core.utils.configuration_cli import configuration_cli_items
from server.application.command.configuration_builtin_support import ConfigurationBuiltinSupport
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


FULL_CONFIG = {
    'store_path': '/tmp/client/runtime_config.json',
    'items': [
        {'key': 'SCRIPT_DEFAULT_OUTPUT_MODE', 'group': 'script', 'value': 'stream',
         'source': 'override', 'default_value': 'collect', 'desc': 'output mode',
         'value_type': 'str', 'choices': ['stream', 'collect'], 'editable': True},
        {'key': 'HTTP_TRANSFER_MODE', 'group': 'transfer', 'value': 'cancelable',
         'source': 'default', 'default_value': 'cancelable', 'desc': 'transfer mode',
         'value_type': 'str', 'choices': ['cancelable'], 'editable': True},
        {'key': 'COMMAND_DEFAULT_SHELL_TIMEOUT', 'group': 'command', 'value': 30,
         'source': 'default', 'default_value': 30, 'desc': 'timeout',
         'value_type': 'int', 'choices': [], 'editable': True},
    ],
}


class Remote:
    def __init__(self, result=None, *, status=1, progress=()):
        self.result = (build_configuration_result(ConfigurationAction.GET, data=FULL_CONFIG)
                       if result is None else result)
        self.status = status
        self.progress = progress
        self.calls = []

    def stream_command(self, conn, command, **kwargs):
        self.calls.append(kwargs)
        from core.protocol.message_queue import ResultChunk
        for msg in self.progress:
            yield ResultChunk(1, msg, False)
        yield ResultChunk(self.status, self.result, True)


def run_config(raw, remote=None):
    remote = remote or Remote()
    conn = SimpleNamespace(session_info=SimpleNamespace(os_alias='linux'))
    support = ConfigurationBuiltinSupport(conn, remote, lambda: '')
    invocation = SERVER_COMMAND_REGISTRY.parse_invocation('config', raw)
    return list(support.config(invocation)), remote


def test_config_view_is_four_fields_sorted_and_does_not_touch_web_data():
    original = json.dumps(FULL_CONFIG, sort_keys=True)
    assert configuration_cli_items(FULL_CONFIG) == [
        {'group': 'command', 'key': 'COMMAND_DEFAULT_SHELL_TIMEOUT', 'value': 30, 'default': 30},
        {'group': 'script', 'key': 'SCRIPT_DEFAULT_OUTPUT_MODE', 'value': 'stream', 'default': 'collect'},
        {'group': 'transfer', 'key': 'HTTP_TRANSFER_MODE', 'value': 'cancelable', 'default': 'cancelable'},
    ]
    assert json.dumps(FULL_CONFIG, sort_keys=True) == original


def test_config_list_text_and_json_same_fields_and_order():
    result, _ = run_config('')
    json_result, remote = run_config('list --json')
    assert len(result) == len(json_result) == 1
    rows = json.loads(json_result[0][1])
    assert rows == configuration_cli_items(FULL_CONFIG)
    assert result[0][0] == json_result[0][0] == 1
    headers = result[0][1].splitlines()[0].lower()
    assert headers.index('group') < headers.index('key') < headers.index('value') < headers.index('default')
    for excluded in ('choices', 'value_type', 'editable', 'store_path', 'override', 'source'):
        assert excluded not in result[0][1] and excluded not in json_result[0][1]
    assert remote.calls[-1]['action'] == ConfigurationAction.GET
    assert remote.calls[-1]['payload'] == {}


@pytest.mark.parametrize('cmd,action,payload', [
    ('set SCRIPT_DEFAULT_OUTPUT_MODE stream --json', ConfigurationAction.SET,
     {'key': 'SCRIPT_DEFAULT_OUTPUT_MODE', 'value': 'stream', 'value_format': 'text'}),
    ('set --key SCRIPT_DEFAULT_OUTPUT_MODE --value stream', ConfigurationAction.SET,
     {'key': 'SCRIPT_DEFAULT_OUTPUT_MODE', 'value': 'stream', 'value_format': 'text'}),
    ('reset SCRIPT_DEFAULT_OUTPUT_MODE', ConfigurationAction.RESET, {'key': 'SCRIPT_DEFAULT_OUTPUT_MODE'}),
    ('reset --key SCRIPT_DEFAULT_OUTPUT_MODE --json', ConfigurationAction.RESET,
     {'key': 'SCRIPT_DEFAULT_OUTPUT_MODE'}),
    ('reset-all --json', ConfigurationAction.RESET, {'all': True}),
])
def test_config_mutation_invocation_and_control(cmd, action, payload):
    result = build_configuration_result(action, message='Updated.')
    output, remote = run_config(cmd, Remote(result))
    assert remote.calls[-1]['payload'] == payload
    assert remote.calls[-1]['action'] == action
    if cmd.endswith('--json'):
        assert json.loads(output[0][1]) == {'status': 'success', 'message': 'Updated.'}
    else:
        assert output[0][1] == 'Updated.'


@pytest.mark.parametrize('cmd', ['--all', 'list --all', 'set KEY --json', 'set --key KEY',
                                  'reset', 'reset KEY VALUE', 'set KEY VAL --value OTHER',
                                  'set KEY VAL --json --json', 'set KEY VALUE EXTRA'])
def test_config_disallows_ambiguous_or_removed_syntax(cmd):
    with pytest.raises(ValueError):
        SERVER_COMMAND_REGISTRY.parse_invocation('config', cmd)


def test_config_error_json_and_empty_view():
    failed = build_configuration_result(ConfigurationAction.GET, status='error', message='Unknown config key')
    output, _ = run_config('list --json', Remote(failed, status=0))
    assert json.loads(output[0][1]) == {'status': 'error', 'message': 'Unknown config key'}
    empty = build_configuration_result(ConfigurationAction.GET, data={'items': []})
    result, _ = run_config('list --json', Remote(empty))
    assert json.loads(result[0][1]) == []
    text, _ = run_config('list', Remote(empty))
    assert text[0][1] == 'No data to display'
