"""Upload autocomplete uses Server paths, not the Client completion command."""
from types import ModuleType
from unittest.mock import patch
import sys
from core.command_completion.parser import CommandCompletionParser
from core.command_completion.models import CompletionSpec
from server.application.command.server_builtin_registry import command, ServerCommandRegistry


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
    registry = ServerCommandRegistry((
        command('upload', 'Upload', raw_tail=True,
                completion=CompletionSpec('filesystem', ('file', 'directory'))),
        command('local_dir', 'List directories', raw_tail=True,
                completion=CompletionSpec('filesystem', ('directory',))),
        command('local_list', 'List paths', raw_tail=True,
                completion=CompletionSpec('filesystem', ('file', 'directory'))),
        command('local_files', 'List files', raw_tail=True,
                completion=CompletionSpec('filesystem', ('file',))),
    ))
    provider = ServerFileSystemCompletionProvider(registry=registry)
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
    only_files = provider.complete(parser.parse(f'local_files {tmp_path}/z'))
    assert [i.insert_text for i in only_files] == [f'local_files {tmp_path}/z test.txt']
    assert not provider.supports(parser.parse('download /tmp/'))


def test_server_filesystem_only_accepts_registered_completion_specs(tmp_path):
    from server.application.completion.command_completion_providers import ServerFileSystemCompletionProvider
    provider = ServerFileSystemCompletionProvider()
    parser = CommandCompletionParser()
    assert provider.supports(parser.parse(f'upload {tmp_path}/'))
    assert not provider.supports(parser.parse(f'download {tmp_path}/'))
    assert not provider.supports(parser.parse(f'gopin go {tmp_path}/'))
    assert not provider.supports(parser.parse(f'xt exec run {tmp_path}/'))


def test_nested_raw_tail_path_keeps_subcommand_prefix(tmp_path):
    from server.application.completion.command_completion_providers import ServerFileSystemCompletionProvider
    from server.application.command.server_builtin_registry import SubcommandSpec
    (tmp_path / 'report.txt').write_text('ok')
    nested = command('local', 'Local', children=(
        SubcommandSpec('choose', 'Choose', raw_tail=True,
                       completion=CompletionSpec('filesystem', ('file', 'directory'))),))
    provider = ServerFileSystemCompletionProvider(registry=ServerCommandRegistry((nested,)))
    context = CommandCompletionParser().parse(f'local choose {tmp_path}/rep')
    assert [item.insert_text for item in provider.complete(context)] == [
        f'local choose {tmp_path}/report.txt']
