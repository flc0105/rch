from core.agent_build_contract import AgentBuilderKind, agent_build_version, agent_output_filename
from core.client_revision import bundle_archive_name, is_bundle_archive
from server.application.agent.agent_output_registry import AgentOutputRegistry


def test_canonical_builder_names_and_build_versions():
    stamp = '20261106_175136_0e8ae4'
    assert set(k.value for k in AgentBuilderKind) == {'python', 'go', 'go_loader'}
    assert agent_build_version('python', stamp) == 'python_' + stamp
    assert agent_build_version('go', stamp) == 'go_' + stamp
    assert agent_build_version('go_loader', stamp) == 'go_loader_' + stamp
    assert bundle_archive_name(stamp) == 'python_' + stamp + '.zip'
    assert is_bundle_archive(bundle_archive_name(stamp))
    assert not is_bundle_archive('rchclient-source-bundle-' + stamp + '.zip')
    assert agent_output_filename('go', stamp, target_os='mac', target_arch='arm64') == 'go_mac_arm64_' + stamp
    assert agent_output_filename('go_loader', stamp, target_os='win', target_arch='amd64', suffix='.exe') == 'go_loader_win_amd64_' + stamp + '.exe'


def test_registry_persists_listener_name_and_id(tmp_path):
    registry = AgentOutputRegistry(str(tmp_path))
    (tmp_path / 'python_test.zip').write_bytes(b'ZIP')
    record = registry.register_output(
        {'file_name': 'python_test.zip', 'build_version': 'python_test', 'builder': 'python'},
        request_payload={'listener_id': 'listener-1', 'listener_name': 'Primary TCP'},
    )
    assert record['listener_id'] == 'listener-1'
    assert record['listener_name'] == 'Primary TCP'
    assert registry.list_outputs()[0]['listener_name'] == 'Primary TCP'
