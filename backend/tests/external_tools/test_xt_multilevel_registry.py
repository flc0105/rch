"""XT fixed commands have one Registry schema; native Exec arguments stay raw."""
import pytest

from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY as REGISTRY


@pytest.mark.parametrize('input_text,action', [
    ('', 'help'), ('help', 'help'), ('exec', 'exec.help'),
    ('exec list --json', 'exec.list'), ('exec info ffmpeg', 'exec.info'),
    ('exec which ffmpeg', 'exec.which'), ('exec ffmpeg --json', 'exec.run'), ('exec run ffmpeg --json', 'exec.run'),
    ('package list --json', 'package.list'), ('package install gost', 'package.install'),
    ('package uninstall gost', 'package.uninstall'), ('module list gost', 'module.list'),
    ('instance create gost.socks5 --id smoke', 'instance.create'),
    ('instance list gost --json', 'instance.list'),
    ('instance start smoke', 'instance.start'),
    ('instance stop smoke', 'instance.stop'),
    ('instance restart smoke', 'instance.restart'),
    ('instance status smoke --json', 'instance.status'),
    ('instance logs smoke -f', 'instance.logs'),
])
def test_all_xt_action_paths_are_recognized(input_text, action):
    inv = REGISTRY.parse_invocation('xt', input_text)
    assert inv.action == action
    assert inv.command == 'xt'


def test_first_parameter_is_named_or_positional():
    a = REGISTRY.parse_invocation('xt', 'instance create gost.socks5 --id rch-smoke')
    b = REGISTRY.parse_invocation('xt', 'instance create --module gost.socks5 --id rch-smoke')
    assert a.arguments == b.arguments
    a = REGISTRY.parse_invocation('xt', 'instance status smoke --module gost.socks5 --json')
    b = REGISTRY.parse_invocation('xt', 'instance status --module gost.socks5 --name smoke --json')
    assert a.arguments == b.arguments
    assert REGISTRY.parse_invocation('xt', 'exec which --name ffmpeg').arguments['name'] == 'ffmpeg'
    assert REGISTRY.parse_invocation('xt', 'module list --package gost').arguments['package'] == 'gost'
    assert REGISTRY.parse_invocation('xt', 'package install --package gost').arguments['package'] == 'gost'


def test_all_preset_and_raw_named_argument_boundaries():
    inv = REGISTRY.parse_invocation('xt',
        'instance create --module gost.socks5 --id local --preset preset-1 --start '
        '-- --listen_ip 127.0.0.1 --listen_port=49173 --description "two  spaces"')
    assert inv.arguments['params'] == {
        'listen_ip': '127.0.0.1', 'listen_port': '49173', 'description': 'two  spaces'}
    assert inv.arguments['start'] is True
    inv = REGISTRY.parse_invocation('xt',
        'instance start --module gost.socks5 --name local -- --listen_port 49174')
    assert inv.arguments['params'] == {'listen_port': '49174'}
    inv = REGISTRY.parse_invocation('xt', 'instance restart local -- --listen_port 49175')
    assert inv.arguments['params'] == {'listen_port': '49175'}


def test_exec_dynamic_raw_tail_never_consumes_native_json_or_quotes():
    dynamic = REGISTRY.parse_invocation('xt', 'exec ffmpeg --json -i "a  b.mp4"')
    assert dynamic.action == 'exec.run'
    assert dynamic.arguments == {'command': 'ffmpeg --json -i "a  b.mp4"'}
    assert dynamic.output_format == 'text'
    direct = REGISTRY.parse_invocation('xt', 'exec ffmpeg  -i \"a b\"  ')
    formal = REGISTRY.parse_invocation('xt', 'exec run ffmpeg  -i \"a b\"  ')
    assert direct.arguments == formal.arguments
    assert direct.arguments['command'] == 'ffmpeg  -i \"a b\"  '
    fixed = REGISTRY.parse_invocation('xt', 'exec list --json')
    assert fixed.action == 'exec.list' and fixed.output_format == 'json'
    with pytest.raises(ValueError):
        REGISTRY.parse_invocation('xt', 'exec list --unknown')


@pytest.mark.parametrize('text', [
    'instance statu smoke', 'package remove gost', 'instance create gost.socks5',
    'instance create --module gost.socks5 --id smoke --params "{}"',
    'instance create gost.socks5 --module gost.socks5 --id smoke',
    'instance create gost.socks5 --id smoke -- --listen_port 1 --listen_port 2',
    'instance create gost.socks5 --id smoke -- --listen_port',
    'instance start local --port 7000',
    'instance start local -- --port',
    'instance status local --follow',
    'instance logs local --json',
    'instance start a b c',
    'exec info',
])
def test_invalid_xt_command_fails_at_registry_boundary(text):
    with pytest.raises(ValueError):
        REGISTRY.parse_invocation('xt', text)


def test_help_independence_and_completion_share_nested_specs():
    assert 'xt instance start' in REGISTRY.help('xt instance')
    assert 'xt instance status' in REGISTRY.help('xt instance status')
    assert 'xt exec which' in REGISTRY.help('xt exec')
    options = [name for name, _ in REGISTRY.completion_paths('xt')]
    assert 'xt instance create ' in options
    assert 'xt instance start ' in options
    assert 'xt package list --installed' in options
    assert 'xt exec ' in options
    assert REGISTRY.is_independent_input('xt instance status local --json') is True
    assert REGISTRY.is_independent_input('xt package list --json') is True
    assert REGISTRY.is_independent_input('xt instance create gost.socks5 --id local') is False


def test_multilevel_registry_uses_shared_token_spans_and_preserves_raw_tail():
    spec, action, tail = REGISTRY.parse('xt', 'instance   status worker1 --json')
    assert action == 'instance.status'
    assert tail == 'worker1 --json'

    spec, action, tail = REGISTRY.parse('xt', 'instance\tstatus\tworker1 --json')
    assert action == 'instance.status'
    assert tail == 'worker1 --json'

    spec, action, tail = REGISTRY.parse('xt', 'exec  ffmpeg  -i "a  b.mp4"  ')
    assert action == 'exec.run'
    assert tail == ' ffmpeg  -i "a  b.mp4"  '
