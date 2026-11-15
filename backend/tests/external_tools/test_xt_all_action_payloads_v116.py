"""Every External Tool action has one deliberately small wire request contract."""
from copy import deepcopy

import pytest

from core.external_tools.payload import client_control_request
from core.protocol.control import ExternalToolAction as A
from server.application.history.activity_definitions import ActivityKind, operation_summary
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


@pytest.fixture
def rich():
    return {
        'tool_id': 'gost.socks5', 'package_id': 'gost', 'module_id': 'socks5',
        'instance_id': 'rch-test', 'display_name': 'GOST SOCKS5',
        'platform': 'mac', 'arch': 'arm64', 'package_key': 'darwin-arm64',
        'version': '3.2.6', 'side': 'client', 'source': 'unused source',
        'instance_name': 'unused', 'execution': 'daemon', 'bogus': 'never transmitted',
        'package': {'filename': 'gost.zip', 'download_url': '/api/archive',
                    'executable_rel_path': 'gost', 'exec_paths': {'gost': 'gost'},
                    'unexpected': 'never transmitted'},
        'install': {'install_dir': '~/.ops/external_tools/installed/gost/3.2.6/darwin-arm64',
                    'skip_if_exists': '~/.ops/external_tools/installed/gost/3.2.6/darwin-arm64/gost',
                    'unexpected': True},
        'params': {'listen_port': 49173},
        'config': {'target': '/managed/gost.conf', 'content': 'listen=49173'},
        'runtime': {'argv': ['/managed/gost'], 'cwd': '/managed', 'stdout': '/managed/stdout.log',
                    'stderr': 'stdout', 'pid_file': '/managed/tool.pid', 'state_file': '/managed/state.json',
                    'unexpected': 'do not send'},
        'launcher': {'type': 'direct'}, 'launcher_override': {'executable': 'python3'},
        'lifecycle': {'stop': {'type': 'signal', 'signal': 'TERM'}},
        'raw_args': '--json -version', 'exec_name': 'gost',
        'exec_options': {'cwd': '/managed', 'timeout_sec': 30, 'arg_mode': 'raw_append',
                         'launcher': {'type': 'direct'}, 'extra': 'drop'},
        'max_bytes': 1024, 'cursor': '5:5:5', 'run_id': 'run-1', 'timeout_sec': 20,
    }


@pytest.mark.parametrize('action,expected', [
    (A.INSTALL_PACKAGE, {'package_id', 'platform', 'arch', 'package_key', 'package', 'install'}),
    (A.UNINSTALL_PACKAGE, {'package_id', 'platform', 'arch', 'package_key', 'install'}),
    (A.GET_INSTALL_STATUSES, {'tools'}),
    (A.CLEAR_PACKAGE_CACHE, {'package_id', 'platform', 'arch', 'package_key', 'package'}),
    (A.RESOLVE_LAUNCHER, {'launcher'}),
    (A.CREATE_INSTANCE, {'tool_id', 'package_id', 'module_id', 'instance_id', 'platform', 'arch', 'package_key', 'params'}),
    (A.READ_INSTANCE, {'tool_id', 'package_id', 'module_id', 'instance_id'}),
    (A.READ_INSTANCE_LOGS, {'tool_id', 'package_id', 'module_id', 'instance_id', 'max_bytes', 'cursor'}),
    (A.START_INSTANCE, {'package_id', 'platform', 'arch', 'package_key', 'package', 'install', 'tool_id',
                        'module_id', 'instance_id', 'display_name', 'params', 'config', 'launcher',
                        'launcher_override', 'install_if_needed', 'runtime'}),
    (A.STOP_INSTANCE, {'tool_id', 'package_id', 'module_id', 'instance_id', 'lifecycle'}),
    (A.RESTART_INSTANCE, {'package_id', 'platform', 'arch', 'package_key', 'package', 'install',
                          'tool_id', 'module_id', 'instance_id', 'display_name', 'params', 'config',
                          'launcher', 'launcher_override', 'install_if_needed', 'runtime', 'lifecycle'}),
    (A.LIST_INSTANCES, {'tools'}),
    (A.REMOVE_INSTANCE, {'tool_id', 'package_id', 'module_id', 'instance_id'}),
    (A.CLEAR_INSTANCE_LOGS, {'tool_id', 'package_id', 'module_id', 'instance_id'}),
    (A.PREVIEW_INSTANCE, {'tool_id', 'package_id', 'module_id', 'instance_id', 'platform',
                          'arch', 'package_key', 'launcher', 'launcher_override', 'runtime'}),
    (A.RUN_ONESHOT, {'package_id', 'platform', 'arch', 'package_key', 'package', 'install', 'tool_id',
                     'display_name', 'config', 'launcher', 'launcher_override',
                     'run_id', 'timeout_sec', 'install_if_needed', 'runtime', 'execution'}),
    (A.EXEC, {'package_id', 'platform', 'arch', 'package_key', 'package', 'install',
              'exec_name', 'raw_args', 'exec_options'}),
])
def test_every_action_has_only_consumer_fields(rich, action, expected):
    data = deepcopy(rich)
    if action in (A.GET_INSTALL_STATUSES, A.LIST_INSTANCES):
        data['tools'] = [deepcopy(rich)]
    result = client_control_request(action, data)
    assert set(result) == expected
    assert 'version' not in result and 'source' not in result and 'side' not in result
    assert 'bogus' not in str(result)
    if action in (A.INSTALL_PACKAGE, A.GET_INSTALL_STATUSES, A.START_INSTANCE, A.RESTART_INSTANCE, A.RUN_ONESHOT, A.EXEC):
        package = result['tools'][0]['package'] if action == A.GET_INSTALL_STATUSES else result['package']
        assert 'unexpected' not in package
        assert ('download_url' in package) == (action == A.INSTALL_PACKAGE)
    if action == A.UNINSTALL_PACKAGE:
        assert result['install'] == {'install_dir': rich['install']['install_dir']}
    if action == A.CLEAR_PACKAGE_CACHE:
        assert result['package'] == {'filename': 'gost.zip'}
    if action in (A.START_INSTANCE, A.RESTART_INSTANCE, A.RUN_ONESHOT):
        assert result['install_if_needed'] is False
        assert 'unexpected' not in result['runtime']
    if action == A.EXEC:
        assert result['exec_options'] == {'cwd': '/managed', 'timeout_sec': 30,
                                          'launcher': {'type': 'direct'}}
    if action == A.LIST_INSTANCES:
        assert set(result['tools'][0]) == {'tool_id', 'package_id', 'module_id', 'instance_id'}


@pytest.mark.parametrize('action,expected', [
    (A.INSTALL_PACKAGE, 'Install gost'), (A.UNINSTALL_PACKAGE, 'Uninstall gost'),
    (A.START_INSTANCE, 'Start gost.socks5 (rch-test)'),
    (A.STOP_INSTANCE, 'Stop gost.socks5 (rch-test)'),
    (A.RESTART_INSTANCE, 'Restart gost.socks5 (rch-test)'),
    (A.EXEC, 'Run gost'), (A.CLEAR_INSTANCE_LOGS, 'Clear logs gost.socks5 (rch-test)'),
    (A.READ_INSTANCE_LOGS, 'Read logs gost.socks5 (rch-test)'),
])
def test_activity_title_uses_real_control_action_and_target(rich, action, expected):
    wire = client_control_request(action, rich)
    assert operation_summary(ActivityKind.EXTERNAL_TOOL, action, wire) == expected
    assert '--module' not in expected and 'External Tool ' not in expected


def test_exec_run_full_and_short_form_are_one_declared_raw_tail():
    registry = SERVER_COMMAND_REGISTRY
    source = 'ffmpeg  -i "a  b.mp4" --json '
    a = registry.parse_invocation('xt', 'exec ' + source)
    b = registry.parse_invocation('xt', 'exec run ' + source)
    assert a == b
    assert a.action == 'exec.run' and a.arguments == {'command': source}
    assert 'xt exec run' in registry.help('xt exec')


def test_uninstall_cannot_escape_client_managed_package_directory(tmp_path, monkeypatch):
    from client.external_tools import installer

    root = tmp_path / 'managed'
    target = root / 'gost' / '3.2.6' / 'darwin-arm64'
    target.mkdir(parents=True)
    (target / 'gost').write_text('isolated smoke test', encoding='utf-8')
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    (unrelated / 'keep.txt').write_text('safe', encoding='utf-8')
    monkeypatch.setattr(installer, 'EXTERNAL_TOOLS_INSTALL_ROOT', str(root))
    service = object.__new__(installer.ExternalToolInstaller)
    monkeypatch.setattr(service, 'validate_package_payload', lambda payload, action: ('mac', 'arm64'))
    monkeypatch.setattr(service, 'has_running_instances_for_package', lambda package_id: False, raising=False)
    valid = {'package_id': 'gost', 'platform': 'mac', 'arch': 'arm64',
             'package_key': 'darwin-arm64', 'install': {'install_dir': str(target)}}
    result = service.uninstall_payload(valid)
    assert result['installed'] is False and result['removed'] is True
    assert not target.exists()
    with pytest.raises(ValueError, match='managed package'):
        service.uninstall_payload({**valid, 'install': {'install_dir': str(unrelated)}})
    assert (unrelated / 'keep.txt').read_text() == 'safe'
