"""Filename-prefix completion must filter before bounded pagination."""
from client.commands.runtime.completion import FileSystemCompletionProvider
from client.runtime.filesystem.file_system_service import FileSystemService
from client.runtime.filesystem.path_resolver import PathResolver
from core.command_completion.models import CompletionSpec


def test_python_client_prefix_after_large_directory_listing(tmp_path, monkeypatch):
    for index in range(75):
        (tmp_path / f'aaa-{index:03d}.zip').write_bytes(b'')
    (tmp_path / 'rchclient_go_loader_mac_arm64.zip').write_bytes(b'ok')
    monkeypatch.chdir(tmp_path)
    resolver = PathResolver()
    provider = FileSystemCompletionProvider(resolver, FileSystemService(resolver))
    candidates = provider.complete('download rchc', len('download rchc'), CompletionSpec('filesystem', ('file', 'directory')))
    assert [item.name for item in candidates] == ['rchclient_go_loader_mac_arm64.zip']
