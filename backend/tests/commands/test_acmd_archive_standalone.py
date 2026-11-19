"""Archive commands reuse Remote File Browser operations and retain safe defaults."""
import json
import os
import zipfile
from types import SimpleNamespace

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
    return ArgumentCommandRegistry(host(socket=SimpleNamespace())).execute(payload)


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
    status, output = run('acmd zip work --json')
    assert status == 1
    archive_path = json.loads(output)['archive_path']
    assert archive_path == str(tmp_path / 'work.zip')
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ['work/hello.txt']

    out = tmp_path / 'restore'; out.mkdir()
    status, output = run('acmd unzip work.zip --dest restore --json')
    assert status == 1
    data = json.loads(output)
    assert data['extracted_to'] == str(out / 'work')
    assert data['file_count'] == 1 and not data['skipped']
    assert (out / 'work' / 'hello.txt').read_text() == 'hello world'


def test_zip_dot_writes_to_parent_not_inside_own_source(tmp_path, monkeypatch):
    work = tmp_path / 'client-data'
    work.mkdir()
    (work / 'a.txt').write_text('a')
    monkeypatch.chdir(work)
    status, output = run('acmd zip . --json')
    assert status == 1
    archive_path = json.loads(output)['archive_path']
    assert archive_path == str(tmp_path / 'client-data.zip')
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ['client-data/a.txt']


def test_custom_destination_and_name_and_txt_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'hello.txt').write_text('hello')
    (tmp_path / 'output').mkdir()
    status, output = run('acmd zip hello.txt -d output -n report --json')
    assert status == 1
    archive_path = json.loads(output)['archive_path']
    assert archive_path == str(tmp_path / 'output' / 'report.zip')
    assert (tmp_path / 'output' / 'report.zip').is_file()
    status, _ = run('acmd zip hello.txt -d output -n report')
    assert status == 0


def test_unzip_conflicts_keep_both_skip_and_replace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'x.txt').write_text('new')
    assert run('acmd zip source')[0] == 1
    (tmp_path / 'target').mkdir()
    output = tmp_path / 'target'
    (output / 'source').mkdir()
    (output / 'source' / 'x.txt').write_text('old')
    status, body = run('acmd unzip source.zip --dest target')
    assert status == 0 and 'already exists' in body.lower()
    assert (output / 'source' / 'x.txt').read_text() == 'old'
    status, body = run('acmd unzip source.zip --dest target --conflict skip --json')
    assert status == 1 and json.loads(body)['skipped'] is True
    status, body = run('acmd unzip source.zip --dest target --conflict keep_both --json')
    assert status == 1
    preserved = json.loads(body)['extracted_to']
    assert preserved != str(output / 'source')
    assert (output / 'source' / 'x.txt').read_text() == 'old'
    status, body = run('acmd unzip source.zip --dest target --conflict replace --json')
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
