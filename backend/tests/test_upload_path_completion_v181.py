"""Upload autocomplete uses Server paths, not the Client completion command."""
from types import ModuleType
from unittest.mock import patch
import sys
from core.command_completion.parser import CommandCompletionParser


def test_upload_server_local_prefix_and_spaces(tmp_path):
    config = ModuleType('server.config.config')
    config.SCRIPT_PATH = str(tmp_path)
    config.COMMAND_HISTORY_RECENT_LIMIT = 100
    with patch.dict(sys.modules, {'server.config.config': config}):
        from server.application.completion.command_completion_providers import ServerFileSystemCompletionProvider
    for i in range(60):
        (tmp_path / f'a{i:02}.txt').touch()
    (tmp_path / 'z test.txt').touch()
    (tmp_path / 'z folder').mkdir()
    provider = ServerFileSystemCompletionProvider(command_names=('upload', 'local_dir', 'local_list'), directory_commands=('local_dir',))
    context = CommandCompletionParser().parse(f'upload {tmp_path}/z', max_results=2)
    assert provider.supports(context)
    items = provider.complete(context)
    assert [(i.insert_text, i.kind) for i in items] == [
        (f'upload {tmp_path}/z folder', 'directory'), (f'upload {tmp_path}/z test.txt', 'file')]
    assert all(i.source == 'server_filesystem' for i in items)

    # Another caller can use exactly the same provider and choose its own scope.
    parser = CommandCompletionParser()
    dirs = provider.complete(parser.parse(f'local_dir {tmp_path}/z'))
    assert [(i.insert_text, i.kind) for i in dirs] == [(f'local_dir {tmp_path}/z folder', 'directory')]
    files = provider.complete(parser.parse(f'local_list {tmp_path}/z'))
    assert {i.insert_text for i in files} == {f'local_list {tmp_path}/z folder', f'local_list {tmp_path}/z test.txt'}
    assert not provider.supports(parser.parse('download /tmp/'))
