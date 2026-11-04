"""Go Loader forwards the selected listener to its downstream Python Bundle."""
from server.application.agent.agent_build_go_loader import GoLoaderBuilder


def test_go_loader_injects_optional_listener_into_go_config(tmp_path):
    source = tmp_path / 'go-loader' / 'config'
    source.mkdir(parents=True)
    config = source / 'config.go'
    config.write_text('package config\n', encoding='utf-8')
    builder = GoLoaderBuilder(str(tmp_path))
    args = (str(tmp_path), 'example.local', 9443, 8085, 'build-1')
    builder._inject_go_loader_config(*args, listener_id='tls-abc123')
    rendered = config.read_text(encoding='utf-8')
    assert 'const ServerListenerID = "tls-abc123"' in rendered
    assert 'const ServerSocketPort = 9443' in rendered
    assert 'const ServerWebPort = 8085' in rendered
    assert 'ServerFileTransferPort' not in rendered
    builder._inject_go_loader_config(*args, listener_id='')
    assert 'const ServerListenerID = ""' in config.read_text(encoding='utf-8')
