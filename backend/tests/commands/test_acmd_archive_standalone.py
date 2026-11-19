"""Archive commands reuse Remote File Browser operations and retain safe defaults."""
import os
import zipfile
from types import SimpleNamespace
from pathlib import Path

import pytest

from client.commands.acmd.common.files import ACMDArchiveCommands
from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.acmd.standalone.zip import zip as archive_zip, ZIP_ARGUMENT_SPEC
from client.commands.acmd.standalone.unzip import unzip, UNZIP_ARGUMENT_SPEC
from client.commands.runtime.hosts import MacCommands, WindowsCommands, LinuxCommands, iOSCommands
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.filesystem.archive_service import ArchiveService
from server.application.command.command_planner import CommandPlanner


def run(text, host=LinuxCommands):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(text)
    return ArgumentCommandRegistry(host(socket=SimpleNamespace(send_event=lambda *_args, **_kwargs: None))).execute(payload)


def test_common_only_mounts_standalone_functions():
    assert ACMDArchiveCommands.zip is archive_zip
    assert ACMDArchiveCommands.unzip is unzip
    assert set(k for k in ACMDArchiveCommands.__dict__ if not k.startswith('__')) == {'zip', 'unzip'}
    assert archive_zip.argument_command_spec is ZIP_ARGUMENT_SPEC
    assert unzip.argument_command_spec is UNZIP_ARGUMENT_SPEC
    assert archive_zip.command_cancel_mode == unzip.command_cancel_mode == 'cooperative'
    for host in (MacCommands, WindowsCommands, LinuxCommands, iOSCommands):
        instance = host(socket=SimpleNamespace())
        assert not hasattr(instance, 'zip_dir')
        reg = ArgumentCommandRegistry(instance)
        assert set(('zip', 'unzip')) <= set(reg._entries)
        assert reg._entries['zip']['handler'].__func__ is archive_zip
        assert reg._entries['unzip']['handler'].__func__ is unzip


def test_zip_default_saves_next_to_source_and_unzip_safely(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'work'
    source.mkdir()
    (source / 'hello.txt').write_text('hello world', encoding='utf8')
    status, output = run('acmd zip work')
    assert status == 1
    archive_path = tmp_path / 'work.zip'
    assert output.startswith('[+] ZIP complete: 1 files, 11 B, ')
    assert output.endswith(str(archive_path))
    assert 'archive_path ' not in output and 'partial ' not in output
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ['work/hello.txt']

    out = tmp_path / 'restore'; out.mkdir()
    status, output = run('acmd unzip work.zip --dest restore')
    assert status == 1
    assert output.startswith('[+] UNZIP complete: 1 files, 11 B, ')
    assert output.endswith(str(out / 'work'))
    assert (out / 'work' / 'hello.txt').read_text() == 'hello world'


def test_zip_dot_writes_to_parent_not_inside_own_source(tmp_path, monkeypatch):
    work = tmp_path / 'client-data'
    work.mkdir()
    (work / 'a.txt').write_text('a')
    monkeypatch.chdir(work)
    status, output = run('acmd zip .')
    assert status == 1
    archive_path = tmp_path / 'client-data.zip'
    assert output.endswith(str(archive_path))
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ['client-data/a.txt']


def test_custom_destination_and_name_and_txt_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'hello.txt').write_text('hello')
    (tmp_path / 'output').mkdir()
    status, output = run('acmd zip hello.txt -d output -n report')
    assert status == 1
    archive_path = tmp_path / 'output' / 'report.zip'
    assert output.endswith(str(archive_path))
    assert archive_path.is_file()
    status, _ = run('acmd zip hello.txt -d output -n report')
    assert status == 0


def test_unzip_conflicts_keep_both_skip_and_replace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'x.txt').write_text('new')
    assert run('acmd zip source')[0] == 1
    output = tmp_path / 'target'; output.mkdir()
    (output / 'source').mkdir()
    (output / 'source' / 'x.txt').write_text('old')
    status, body = run('acmd unzip source.zip --dest target')
    assert status == 0 and 'already exists' in body.lower()
    assert (output / 'source' / 'x.txt').read_text() == 'old'
    status, body = run('acmd unzip source.zip --dest target --conflict skip')
    assert status == 1 and body.startswith('[!] UNZIP skipped:')
    assert body.endswith(str(output / 'source'))
    status, body = run('acmd unzip source.zip --dest target --conflict keep_both')
    assert status == 1 and body.startswith('[+] UNZIP complete:')
    preserved = Path(body.splitlines()[-1])
    assert preserved.parent == output and preserved.name != 'source'
    assert (preserved / 'x.txt').read_text() == 'new'
    assert (output / 'source' / 'x.txt').read_text() == 'old'
    status, body = run('acmd unzip source.zip --dest target --conflict replace')
    assert status == 1 and (output / 'source' / 'x.txt').read_text() == 'new'


def test_existing_archive_rejected_without_clobber(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'x').write_text('x')
    assert run('acmd zip source')[0] == 1
    data = (tmp_path / 'source.zip').read_bytes()
    status, text = run('acmd zip source')
    assert status == 0 and 'already exists' in text.lower()
    assert (tmp_path / 'source.zip').read_bytes() == data


def test_archive_destination_inside_source_is_refused_for_all_users(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'x').write_text('x')
    status, text = run('acmd zip source --dest source')
    assert status == 0 and 'inside an archived directory' in text
    assert not (source / 'source.zip').exists()
    svc = ArchiveService(__import__('client.runtime.filesystem.path_resolver', fromlist=['PathResolver']).PathResolver())
    with pytest.raises(ValueError, match='inside an archived directory'):
        svc.create_zip_in_directory([str(source)], str(source))


def test_unzip_blocks_zip_slip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with zipfile.ZipFile(tmp_path / 'evil.zip', 'w') as archive:
        archive.writestr('../outside.txt', 'unsafe')
    status, body = run('acmd unzip evil.zip')
    assert status == 0
    assert not (tmp_path / 'outside.txt').exists()
    assert not (tmp_path.parent / 'outside.txt').exists()


def test_invalid_cli_args_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for statement in ('acmd zip', 'acmd zip --unknown x', 'acmd unzip',
                      'acmd unzip a.zip --conflict dangerous'):
        status, _ = run(statement)
        assert status == 0
    assert run('acmd zip --help')[0] == 1
    assert run('acmd unzip --help')[0] == 1


def test_interruption_is_not_hidden_by_generic_registry_error(monkeypatch):
    def cancel(self, args, payload=None):
        raise CommandCancelledError('Command cancelled')
    def timeout(self, args, payload=None):
        raise CommandTimeoutError('Command timed out')
    reg = ArgumentCommandRegistry(LinuxCommands(socket=SimpleNamespace()))
    reg._entries['zip']['handler'] = cancel.__get__(LinuxCommands(socket=SimpleNamespace()))
    with pytest.raises(CommandCancelledError):
        reg.execute({'name': 'zip', 'args': {'path': 'ignored'}})
    reg._entries['zip']['handler'] = timeout.__get__(LinuxCommands(socket=SimpleNamespace()))
    with pytest.raises(CommandTimeoutError):
        reg.execute({'name': 'zip', 'args': {'path': 'ignored'}})


def test_named_path_zip_and_unzip_shortcut_flags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'new.txt').write_text('updated')
    status, body = run('acmd zip --path source -n snapshot.zip -v')
    assert status == 1 and body.startswith('[+] ZIP complete: 1 files, ')
    (tmp_path / 'restore').mkdir()
    status, body = run('acmd unzip --path snapshot.zip -d restore -v')
    assert status == 1 and body.startswith('[+] UNZIP complete: 1 files, ')
    existing = tmp_path / 'restore' / 'source' / 'new.txt'
    existing.write_text('old')
    status, body = run('acmd unzip snapshot.zip -d restore --skip')
    assert status == 1 and body.startswith('[!] UNZIP skipped:')
    assert existing.read_text() == 'old'
    status, body = run('acmd unzip snapshot.zip -d restore --merge')
    assert status == 1 and body.startswith('[+] UNZIP complete:')
    assert existing.read_text() == 'updated'
    for cli in ('acmd unzip snapshot.zip --merge --skip',
                'acmd unzip snapshot.zip --merge --conflict stop',
                'acmd unzip snapshot.zip --skip --conflict merge'):
        status, body = run(cli)
        assert status == 0 and 'Choose one conflict strategy' in body
    status, body = run('acmd unzip --conflict replace --path snapshot.zip -d restore')
    assert status == 1 and body.startswith('[+] UNZIP complete:')


def test_missing_path_and_help_spellings():
    assert 'Missing required argument: <path>' in run('acmd zip')[1]
    assert 'Missing required argument: <path>' in run('acmd unzip')[1]
    assert 'acmd zip <path>' in run('acmd zip --help')[1]
    assert '--skip-unreadable' in run('acmd zip --help')[1]
    assert '--merge' in run('acmd unzip --help')[1]
    assert '--skip' in run('acmd unzip --help')[1]
    assert 'acmd unzip <path>' in run('acmd unzip --help')[1]
    assert run('acmd zip --path --name file.zip')[0] == 0


def test_zip_progress_default_and_verbose(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'one.txt').write_text('one')
    (source / 'two.txt').write_text('two')

    def invoke(text):
        events = []
        socket = SimpleNamespace(send_event=lambda cid, event: events.append(event))
        registry = ArgumentCommandRegistry(LinuxCommands(socket=socket))
        status, body = registry.execute(CommandPlanner.__new__(CommandPlanner).parse_argument_command(text))
        return status, body, [event['message'] for event in events if event['event_type'] == 'progress']

    status, body, events = invoke('acmd zip source -n simple.zip')
    assert status == 1 and body.startswith('[+] ZIP complete: 2 files, 6 B, ')
    assert body.endswith(str(tmp_path / 'simple.zip'))
    assert events == []

    status, body, events = invoke('acmd zip source -n verbose.zip -v')
    assert status == 1 and body.startswith('[+] ZIP complete: 2 files, ')
    assert sum('ZIP file:' in event for event in events) == 2
    assert any('ZIP: ' in event for event in events)
    assert not any('ZIP complete:' in event for event in events)

    (tmp_path / 'restore').mkdir()
    status, body, events = invoke('acmd unzip verbose.zip -d restore')
    assert status == 1 and body.startswith('[+] UNZIP complete: 2 files, ')
    assert events == []
    (tmp_path / 'restore2').mkdir()
    status, body, events = invoke('acmd unzip verbose.zip -d restore2 -v')
    assert status == 1 and sum('UNZIP file:' in event for event in events) == 2
    assert not any('UNZIP complete:' in event for event in events)


def test_zip_unreadable_strict_and_explicit_partial(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'readable.txt').write_text('yes')
    (source / 'blocked.txt').write_text('secret')
    original_write = zipfile.ZipFile.write

    def reject_blocked(self, filename, *args, **kwargs):
        if str(filename).endswith('blocked.txt'):
            raise PermissionError(13, 'Permission denied', str(filename))
        return original_write(self, filename, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'write', reject_blocked)
    status, body = run('acmd zip source -n strict.zip')
    assert status == 0 and 'blocked.txt' in body and 'skip-unreadable' in body
    assert not (tmp_path / 'strict.zip').exists()

    events = []
    socket = SimpleNamespace(send_event=lambda cid, event: events.append(event))
    status, body = ArgumentCommandRegistry(LinuxCommands(socket=socket)).execute(
        CommandPlanner.__new__(CommandPlanner).parse_argument_command(
            'acmd zip source -n partial.zip --skip-unreadable'))
    assert status == 1 and body.startswith('[+] ZIP partial: 1 files, 3 B, ')
    assert '(skipped 1 unreadable)' in body
    assert body.endswith(str(tmp_path / 'partial.zip'))
    assert any('blocked.txt' in event['message'] and event['event_type'] == 'progress'
               for event in events)
    with zipfile.ZipFile(tmp_path / 'partial.zip') as archive:
        assert archive.namelist() == ['source/readable.txt']

    status, body = run('acmd zip --path source/blocked.txt -n empty.zip --skip-unreadable')
    assert status == 0 and 'no readable files' in body
    assert not (tmp_path / 'empty.zip').exists()


def test_zip_directory_scan_error_is_not_silent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'good.txt').write_text('good')
    (source / 'private').mkdir()
    original_walk = os.walk

    def simulate_walk(top, *args, **kwargs):
        if str(top) != str(source):
            yield from original_walk(top, *args, **kwargs)
            return
        yield str(source), ['private'], ['good.txt']
        callback = kwargs.get('onerror')
        if callback:
            callback(PermissionError(13, 'Permission denied', str(source / 'private')))

    monkeypatch.setattr(os, 'walk', simulate_walk)
    status, body = run('acmd zip source -n strict.zip')
    assert status == 0 and 'private' in body
    assert not (tmp_path / 'strict.zip').exists()
    status, body = run('acmd zip source -n partial.zip --skip-unreadable')
    assert status == 1 and '(skipped 1 unreadable)' in body


def test_archive_json_is_not_supported_and_help_only_advertises_verbose():
    zip_help = run('acmd zip --help')[1]
    unzip_help = run('acmd unzip --help')[1]
    assert '--verbose' in zip_help and '--verbose' in unzip_help
    assert '--json' not in zip_help and '--json' not in unzip_help
    assert run('acmd zip --path . --json')[0] == 0
    assert run('acmd unzip --path file.zip --json')[0] == 0


def test_zip_uses_existing_human_readable_size_formatter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'large.bin').write_bytes(b'x' * 2048)
    status, output = run('acmd zip large.bin')
    assert status == 1 and '2 KB' in output
    assert '2048' not in output
    assert output.splitlines()[-1] == str(tmp_path / 'large.bin.zip')


def test_remote_archive_service_default_call_is_unchanged(tmp_path, monkeypatch):
    from client.runtime.filesystem.path_resolver import PathResolver
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'item.txt').write_text('payload')
    service = ArchiveService(PathResolver())
    archive_path = service.create_zip_in_directory([str(source)], str(tmp_path))
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ['source/item.txt']
    assert service.extract_zip_with_policy(archive_path, str(tmp_path / 'output')
        if (tmp_path / 'output').exists() else str(tmp_path), policy='keep_both')['file_count'] == 1
