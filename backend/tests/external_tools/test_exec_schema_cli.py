"""Public Exec exports are separate from internal service binaries and modules."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.external_tools.meta import normalize_meta
from core.external_tools.selector import resolve_binary_rel_path
from core.protocol.structured_arg_codec import decode_structured_arg
from server.application.command.external_tool_cli_builtin_support import ExternalToolCliBuiltinSupport
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService


METAS = Path(__file__).resolve().parents[2] / 'server/resources/external_tools/metas'


def catalog():
    return ExternalToolCatalogService(str(METAS), str(METAS.parent / 'packages'))


def test_all_meta_use_only_canonical_binary_mapping():
    packages = [normalize_meta(json.loads(p.read_text(encoding='utf-8'))) for p in METAS.glob('*.json')]
    assert len(packages) == 16
    for pkg in packages:
        assert pkg['binaries']
        assert 'exec' not in pkg
        for module in pkg['modules']:
            assert 'exec' not in module
            assert module['binary'] in pkg['binaries']
        assert set(pkg.get('execs', {})) == {'ffmpeg': {'ffmpeg'}, 'python-embed': {'python'}}.get(pkg['id'], set())
        for published in pkg.get('execs', {}).values():
            assert published['binary'] in pkg['binaries']
            assert 'paths' not in published
    assert [(t['exec_name'], t['executable_rel_path']) for t in catalog().list_exec_targets('mac', 'amd64')] == [('ffmpeg', 'ffmpeg')]
    assert [(t['exec_name'], t['executable_rel_path']) for t in catalog().list_exec_targets('win', 'amd64')] == [
        ('ffmpeg', 'bin/ffmpeg.exe'), ('python', 'python.exe'),
    ]
    assert catalog().list_exec_targets('linux', 'amd64') == []


def test_no_legacy_exec_metadata_or_unknown_binary_allowed():
    sample = json.loads((METAS / 'ffmpeg.json').read_text(encoding='utf-8'))
    sample['modules'][0].pop('binary')
    with pytest.raises(ValueError, match='unknown binary'):
        normalize_meta(sample)
    sample = json.loads((METAS / 'ffmpeg.json').read_text(encoding='utf-8'))
    sample['execs']['ffmpeg']['binary'] = 'does-not-exist'
    with pytest.raises(ValueError, match='unknown binary'):
        normalize_meta(sample)
    sample = json.loads((METAS / 'ffmpeg.json').read_text(encoding='utf-8'))
    sample['modules'][0]['exec'] = sample['modules'][0]['binary']
    with pytest.raises(ValueError, match='deprecated exec'):
        normalize_meta(sample)
    sample = json.loads((METAS / 'ffmpeg.json').read_text(encoding='utf-8'))
    sample['execs']['ffmpeg']['paths'] = {'mac-amd64': 'ffmpeg'}
    with pytest.raises(ValueError, match='must only export a binary'):
        normalize_meta(sample)
    sample = json.loads((METAS / 'ffmpeg.json').read_text(encoding='utf-8'))
    sample.pop('binaries')
    with pytest.raises(ValueError, match='binaries is required'):
        normalize_meta(sample)


def test_cli_only_packages_can_omit_modules():
    sample = json.loads((METAS / 'ffmpeg.json').read_text(encoding='utf-8'))
    sample.pop('modules')
    assert normalize_meta(sample)['modules'] == []
    sample.pop('execs')
    with pytest.raises(ValueError, match='modules or execs'):
        normalize_meta(sample)


def test_service_binary_launcher_survives_without_exec_export():
    pkg = catalog().get_package('java-bundle-demo')
    assert not pkg.get('execs')
    assert resolve_binary_rel_path(pkg, 'java-bundle-demo', 'common-all') == 'java-bundle-demo.jar'
    module = catalog().get_tool('java-bundle-demo.web')
    builder = ExternalToolRuntimeService(catalog(), command_execution_api=None).payload_builder
    payload = builder.build_client_start_payload(module, platform_alias='win', arch='amd64')
    assert payload['launcher']['command'] == 'java'
    assert payload['package']['exec_paths']['java-bundle-demo'] == 'java-bundle-demo.jar'
    assert payload['package']['executable_rel_path'] == 'java-bundle-demo.jar'
    # Oneshot modules are still available even if not exported as a direct Exec.
    python_module = catalog().get_tool('python-embed.test')
    oneshot = builder.build_client_oneshot_payload(python_module, platform_alias='win', arch='amd64')
    assert oneshot['package']['executable_rel_path'] == 'python.exe'
    assert catalog().get_package('python-embed')['execs']['python']['binary'] == 'python'


class CliProbe(ExternalToolCliBuiltinSupport):
    def __init__(self):
        self.captured = []
        self.conn = SimpleNamespace(session_info=SimpleNamespace(os_alias='mac', arch='amd64', cwd='/tmp'))
        self.server = SimpleNamespace(web_service=SimpleNamespace(assembly=SimpleNamespace(
            external_tool_catalog_service=catalog(),
            external_tool_runtime_service=ExternalToolRuntimeService(catalog(), command_execution_api=None),
        )))
        self.command_processor_factory = None
        self.history_entry_id_provider = lambda: ''

    def _collect_nested_command_text(self, command_text):
        self.captured.append(command_text)
        return 1, json.dumps({'items': [{'installed': True, 'install_status': 'installed'}]})

    def _iter_nested_command(self, command_text):
        self.captured.append(command_text)
        yield 1, 'mock command succeeded'


def test_xt_exec_routes_and_raw_argument_tail():
    cli = CliProbe()
    assert list(cli.xt('exec list'))[0][0] == 1
    status, data = next(cli.xt('exec list --json'))
    assert status == 1
    assert json.loads(data) == [{'exec_name': 'ffmpeg', 'package_id': 'ffmpeg'}]
    status, table = next(cli.xt('exec list'))
    assert status == 1
    assert table.splitlines()[0].rstrip() == 'EXEC   | PACKAGE'
    assert 'ffmpeg | ffmpeg' in table
    assert next(cli.xt('exec info ffmpeg'))[0] == 1
    assert next(cli.xt('exec which ffmpeg')) == (1, 'mock command succeeded')

    for args, expected in [
        ('-- -i "Some Clip.mp4" -f null -', '-i "Some Clip.mp4" -f null -'),
        ('--json', '--json'),
        ('-version', '-version'),
        ('-- --json', '--json'),
    ]:
        assert next(cli.xt('exec ffmpeg ' + args)) == (1, 'mock command succeeded')
        command, encoded_payload = cli.captured[-1].split(' ', 1)
        assert command == 'external_tool_exec'
        assert decode_structured_arg(encoded_payload)['raw_args'] == expected
    for invalid in ['run ffmpeg -version', 'ffmpeg -version', 'which ffmpeg', 'list', 'info ffmpeg']:
        with pytest.raises(ValueError):
            SERVER_COMMAND_REGISTRY.parse('xt', invalid)
    for valid in ['exec ffmpeg --json', 'exec list --json', 'exec info ffmpeg', 'exec which ffmpeg']:
        assert SERVER_COMMAND_REGISTRY.parse('xt', valid)[1] == 'exec'


def test_python_embed_cli_exec_is_windows_only_and_passes_native_arguments():
    cli = CliProbe()
    cli.conn.session_info.os_alias = 'win'
    cli.conn.session_info.cwd = r'C:\Work Folder'
    cli._collect_nested_command_text = lambda _: (1, json.dumps({'items': [
        {'installed': True, 'install_status': 'installed'},
        {'installed': True, 'install_status': 'installed'},
    ]}))
    status, data = next(cli.xt('exec list --json'))
    assert status == 1
    assert json.loads(data) == [
        {'exec_name': 'ffmpeg', 'package_id': 'ffmpeg'},
        {'exec_name': 'python', 'package_id': 'python-embed'},
    ]
    status, table = next(cli.xt('exec list'))
    assert status == 1
    assert table.splitlines()[0].rstrip() == 'EXEC   | PACKAGE'
    assert 'python | python-embed' in table
    assert next(cli.xt('exec info python --json'))[0] == 1
    assert next(cli.xt('exec which python')) == (1, 'mock command succeeded')
    for args, raw_args in [
        ('-V', '-V'),
        ('-- -c "print(1 + 1)"', '-c "print(1 + 1)"'),
        ('--json', '--json'),
    ]:
        assert next(cli.xt('exec python ' + args)) == (1, 'mock command succeeded')
        command, encoded_payload = cli.captured[-1].split(' ', 1)
        assert command == 'external_tool_exec'
        payload = decode_structured_arg(encoded_payload)
        assert payload['package_id'] == 'python-embed'
        assert payload['exec_name'] == 'python'
        assert payload['package']['executable_rel_path'] == 'python.exe'
        assert payload['raw_args'] == raw_args


def test_xt_exec_list_only_installed():
    cli = CliProbe()
    cli._collect_nested_command_text = lambda _: (1, json.dumps({'items': [{'installed': False, 'install_status': 'not_installed'}]}))
    status, text = next(cli.xt('exec list --json'))
    assert status == 1 and json.loads(text) == []
    status, text = next(cli.xt('exec list'))
    assert status == 1 and 'No installed external tool' in text


def test_client_sdk_only_resolves_public_execs(monkeypatch):
    from client.runtime.sdk import xt as sdk

    packages = catalog().list_packages()
    monkeypatch.setattr(sdk, '_iter_packages', lambda: iter(packages))
    monkeypatch.setattr(sdk, '_target_platform', lambda: 'mac')
    monkeypatch.setattr(sdk, '_target_arch', lambda: 'amd64')
    ffmpeg = sdk._build_exec_payload('ffmpeg', raw_args='-version')
    assert ffmpeg['package']['executable_rel_path'] == 'ffmpeg'
    assert ffmpeg['package']['exec_paths'] == {'ffmpeg': 'ffmpeg'}
    assert ffmpeg['raw_args'] == '-version'
    with pytest.raises(sdk.ScriptSdkExternalToolError, match='not found'):
        sdk._resolve_exec_target('python')
    with pytest.raises(sdk.ScriptSdkExternalToolError, match='not found'):
        sdk._resolve_exec_target('frpc')

    monkeypatch.setattr(sdk, '_target_platform', lambda: 'win')
    python = sdk._build_exec_payload('python', raw_args='-V')
    assert python['exec_name'] == 'python'
    assert python['package_id'] == 'python-embed'
    assert python['package']['executable_rel_path'] == 'python.exe'
    assert python['package']['exec_paths'] == {'python': 'python.exe'}
    assert python['raw_args'] == '-V'
    with pytest.raises(sdk.ScriptSdkExternalToolError, match='not found'):
        sdk._resolve_exec_target('frpc')

