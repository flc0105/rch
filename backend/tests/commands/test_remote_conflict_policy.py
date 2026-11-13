"""Remote file conflict policies must preserve unrelated files and guard writes."""
import zipfile

import pytest

from client.commands.common.services.filesystem.archive_service import ArchiveService
from client.commands.common.services.filesystem.conflict_policy import (
    apply_path, commit_download_file, describe_conflict, prepare_upload_file_commit,
)
from client.commands.common.services.filesystem.file_system_service import FileSystemService
from client.commands.common.services.filesystem.path_resolver import PathResolver


def test_file_conflict_stop_replace_and_keep_both(tmp_path):
    src = tmp_path / 'source' / 'report.txt'
    dest = tmp_path / 'target' / 'report.txt'
    src.parent.mkdir();dest.parent.mkdir()
    src.write_text('new');dest.write_text('old')
    conflict = describe_conflict(str(src), str(dest))
    assert conflict['allowed_actions'] == ['stop', 'skip', 'replace', 'keep_both']
    with pytest.raises(FileExistsError):
        apply_path(str(src), str(dest), 'copy', 'stop')
    assert dest.read_text() == 'old'
    kept = apply_path(str(src), str(dest), 'copy', 'keep_both')
    assert kept != str(dest) and kept.endswith('.txt') and '_20' in kept
    assert dest.read_text() == 'old'
    assert __import__('pathlib').Path(kept).read_text() == 'new'
    apply_path(str(src), str(dest), 'copy', 'replace')
    assert dest.read_text() == 'new' and src.read_text() == 'new'


def test_directory_merge_preserves_unrelated_replace_removes(tmp_path):
    source = tmp_path / 'source' / 'work'
    target = tmp_path / 'target' / 'work'
    source.mkdir(parents=True);target.mkdir(parents=True)
    (source / 'common.txt').write_text('NEW')
    (source / 'only-new.txt').write_text('new')
    (target / 'common.txt').write_text('OLD')
    (target / 'only-old.txt').write_text('old')
    assert describe_conflict(str(source), str(target))['allowed_actions'] == ['stop', 'skip', 'merge', 'replace', 'keep_both']
    apply_path(str(source), str(target), 'copy', 'merge')
    assert (target / 'common.txt').read_text() == 'NEW'
    assert (target / 'only-old.txt').read_text() == 'old'
    assert (source / 'common.txt').read_text() == 'NEW'
    apply_path(str(source), str(target), 'copy', 'replace')
    assert not (target / 'only-old.txt').exists()
    assert (target / 'only-new.txt').read_text() == 'new'


def test_move_directory_merge_removes_source_only_after_success(tmp_path):
    src = tmp_path / 'from' / 'd';dst=tmp_path / 'to' / 'd'
    src.mkdir(parents=True);dst.mkdir(parents=True)
    (src/'updated').write_text('new');(dst/'untouched').write_text('old')
    apply_path(str(src),str(dst),'move','merge')
    assert not src.exists() and (dst/'updated').read_text()=='new' and (dst/'untouched').read_text()=='old'


def test_type_conflict_only_stop_or_keep_both(tmp_path):
    src=tmp_path/'a';dst=tmp_path/'b';src.write_text('file');dst.mkdir()
    assert describe_conflict(str(src), str(dst))['allowed_actions'] == ['stop', 'skip','keep_both']
    for policy in ('merge','replace'):
        with pytest.raises(FileExistsError):apply_path(str(src),str(dst),'copy',policy)
    kept=apply_path(str(src),str(dst),'copy','keep_both')
    assert __import__('pathlib').Path(kept).read_text()=='file' and dst.is_dir()


def test_merge_nested_type_collision_leaves_original_tree(tmp_path):
    src=tmp_path/'src';dst=tmp_path/'dst';src.mkdir();dst.mkdir()
    (src/'same').write_text('new');(dst/'same').mkdir()
    (src/'alpha').write_text('alpha')
    with pytest.raises(FileExistsError):apply_path(str(src),str(dst),'copy','merge')
    assert not (dst/'alpha').exists() and (dst/'same').is_dir()


def test_paste_inspect_no_side_effect_and_policy_execution(tmp_path):
    root=tmp_path/'root';dest=tmp_path/'dest';root.mkdir();dest.mkdir()
    original=root/'x.txt';original.write_text('source')
    (dest/'x.txt').write_text('old')
    svc=FileSystemService(PathResolver())
    preview=svc.paste_paths([str(original)], str(dest),'copy', inspect=True)
    assert preview['conflicts'][0]['index']==0
    assert (dest/'x.txt').read_text()=='old'
    result=svc.paste_paths([str(original)],str(dest),'copy', policies=['keep_both'])
    assert result.succeeded==1
    assert (dest/'x.txt').read_text()=='old' and len(list(dest.iterdir()))==2


def test_zip_extract_entry_merge_and_full_replace(tmp_path):
    archive=tmp_path/'archive.zip'
    with zipfile.ZipFile(archive,'w') as out:
        out.writestr('root/shared.txt','new')
        out.writestr('root/new.txt','new')
    dest=tmp_path/'dest';dest.mkdir()
    (dest/'root').mkdir();(dest/'root'/'old.txt').write_text('old')
    (dest/'root'/'shared.txt').write_text('OLD')
    service=ArchiveService(PathResolver())
    preview=service.inspect_extract_target(str(archive), str(dest))
    assert preview['conflicts'][0]['allowed_actions']==['stop','skip','merge','replace','keep_both']
    service.extract_zip_with_policy(str(archive),str(dest),policy='merge')
    assert (dest/'root'/'old.txt').read_text()=='old'
    assert (dest/'root'/'shared.txt').read_text()=='new'
    service.extract_zip_with_policy(str(archive),str(dest),policy='replace')
    assert not (dest/'root'/'old.txt').exists()
    assert (dest/'root'/'new.txt').read_text()=='new'
    entry=service.extract_zip_with_policy(str(archive),str(dest),'root/new.txt','keep_both')
    assert (dest/'new.txt').read_text()=='new' and entry['extracted_to']==str(dest/'new.txt')
    extra=service.extract_zip_with_policy(str(archive),str(dest),'root/new.txt','keep_both')
    assert extra['extracted_to'] != str(dest/'new.txt') and __import__('pathlib').Path(extra['extracted_to']).read_text()=='new'


def test_upload_commit_existing_file_and_directory(tmp_path):
    original=tmp_path/'data.txt';original.write_text('original')
    incoming=tmp_path/'staged1';incoming.write_text('new')
    with pytest.raises(FileExistsError):commit_download_file(str(incoming),str(original),'stop')
    assert original.read_text()=='original' and incoming.exists()
    kept=commit_download_file(str(incoming),str(original),'keep_both')
    assert original.read_text()=='original' and __import__('pathlib').Path(kept).read_text()=='new'
    incoming=tmp_path/'staged2';incoming.write_text('replace')
    commit_download_file(str(incoming),str(original),'replace')
    assert original.read_text()=='replace'
    folder=tmp_path/'folder';folder.mkdir()
    incoming=tmp_path/'staged3';incoming.write_text('file')
    with pytest.raises(FileExistsError):commit_download_file(str(incoming),str(folder),'replace')
    assert folder.is_dir()


def test_upload_conflict_policy_is_validated_before_transfer(tmp_path):
    target = tmp_path / 'upload.txt'
    for invalid in ('merge', 'skip', '', None, 42):
        with pytest.raises(ValueError, match='Invalid upload conflict policy'):
            prepare_upload_file_commit(str(target), invalid)
        staged = tmp_path / 'staged.txt'
        staged.write_text('new')
        with pytest.raises(ValueError, match='Invalid upload conflict policy'):
            commit_download_file(str(staged), str(target), invalid)
        assert not target.exists() and staged.read_text() == 'new'

    publish = prepare_upload_file_commit(str(target), 'stop')
    staged = tmp_path / 'staged.txt'
    staged.write_text('new')
    assert publish(str(staged)) == str(target)
    assert target.read_text() == 'new'


def test_upload_transfer_rejects_invalid_policy_without_creating_folder(tmp_path):
    from types import SimpleNamespace
    from client.transfers.manager import ClientTransferManager
    from client.commands.common.services.filesystem.path_resolver import PathResolver

    destination = tmp_path / 'absent'
    called = []

    class FakeService:
        def download_file_from_http(self, *args, **kwargs):
            called.append((args, kwargs))
            with open(args[1], 'wb') as stream:
                stream.write(b'new data')
            if kwargs.get('commit'):
                kwargs['commit'](args[1])

    owner = SimpleNamespace(
        path_resolver=PathResolver(),
        client_api=SimpleNamespace(normalize_file_transfer_url=lambda url: url),
        execution_context=None,
    )
    manager = ClientTransferManager(connection=None)
    invalid = {
        'url': 'http://localhost/test', 'filename': 'upload.txt',
        'save_dir': str(destination), 'conflict_policy': 'merge',
    }
    with pytest.raises(ValueError, match='Invalid upload conflict policy'):
        manager._run_server_to_client_file(FakeService(), owner, 'transfer-1', invalid)
    assert not destination.exists() and not called

    valid = {**invalid, 'conflict_policy': 'stop'}
    manager._run_server_to_client_file(FakeService(), owner, 'transfer-2', valid)
    assert (destination / 'upload.txt').read_bytes() == b'new data'
    assert len(called) == 1


def test_default_upload_rejects_existing_without_starting_transfer(tmp_path):
    from types import SimpleNamespace
    from client.transfers.manager import ClientTransferManager

    destination = tmp_path / 'target'
    destination.mkdir()
    existing = destination / 'asset.dat'
    existing.write_bytes(b'original')
    calls = []

    class FakeService:
        def download_file_from_http(self, *args, **kwargs):
            calls.append(args)
            with open(args[1], 'wb') as stream:
                stream.write(b'incoming')
            kwargs['commit'](args[1])

    owner = SimpleNamespace(
        path_resolver=PathResolver(),
        client_api=SimpleNamespace(normalize_file_transfer_url=lambda url: url),
        execution_context=None,
    )
    manager = ClientTransferManager(connection=None)
    request = {'url': 'http://localhost/sample', 'filename': 'asset.dat', 'save_dir': str(destination)}
    with pytest.raises(FileExistsError):
        manager._run_server_to_client_file(FakeService(), owner, 't', request)
    assert existing.read_bytes() == b'original'
    assert not calls
    assert sorted(x.name for x in destination.iterdir()) == ['asset.dat']

    # Explicit selection is the only path to replacing a remote file.
    manager._run_server_to_client_file(FakeService(), owner, 't2', {**request, 'conflict_policy': 'replace'})
    assert existing.read_bytes() == b'incoming'


def test_default_zip_extract_rejects_existing_without_auto_rename(tmp_path):
    archive = tmp_path / 'archive.zip'
    with zipfile.ZipFile(archive, 'w') as handle:
        handle.writestr('notes.txt', 'new')
    dest = tmp_path / 'dest'
    dest.mkdir()
    existing = dest / 'archive'
    existing.mkdir()
    (existing / 'keep.txt').write_text('old')
    service = ArchiveService(PathResolver())
    with pytest.raises(FileExistsError):
        service.extract_zip_with_policy(str(archive), str(dest), policy='stop')
    assert (existing / 'keep.txt').read_text() == 'old'
    assert [x.name for x in dest.iterdir()] == ['archive']


def test_artifact_send_forwards_only_explicit_upload_policy(tmp_path):
    from types import SimpleNamespace
    from server.application.web.artifact_api import WebArtifactApi

    calls = []
    fake = SimpleNamespace(
        get_artifact_by_id=lambda item: {'artifact_type': 'shared_files', 'original_name': 'sample.bin'},
        get_artifact_file_path=lambda item: str(tmp_path / 'sample.bin'),
    )
    command_api = SimpleNamespace(submit_web_upload=lambda *args, **kwargs: calls.append((args, kwargs)) or {'task_id': 'task-1'})
    api = WebArtifactApi(None, None, fake, command_execution_api=command_api)
    result = api.send_artifact_to_client('id', 'device', '/dest')
    assert result['task_id'] == 'task-1'
    assert calls[-1][1]['conflict_policy'] == 'stop'
    api.send_artifact_to_client('id', 'device', '/dest', conflict_policy='keep_both')
    assert calls[-1][1]['conflict_policy'] == 'keep_both'
    with pytest.raises(ValueError, match='Invalid upload conflict policy'):
        api.send_artifact_to_client('id', 'device', '/dest', conflict_policy='merge')
    assert len(calls) == 2


def test_remote_zip_api_defaults_to_explicit_stop(monkeypatch):
    from types import SimpleNamespace
    from server.application.artifact.remote_file_service import WebRemoteFileService
    svc = WebRemoteFileService(SimpleNamespace(), None)
    submissions = []
    def record(*args, **kwargs):
        submissions.append((args, kwargs))
        return {'extracted_to': '/dst/archive'}
    monkeypatch.setattr(svc, '_run_mutation', record)
    svc.extract_zip('client', '/archive.zip', '/dst')
    assert submissions[-1][0][3]['conflict_policy'] == 'stop'
    svc.extract_zip('client', '/archive.zip', '/dst', conflict_policy='merge')
    assert submissions[-1][0][3]['conflict_policy'] == 'merge'


def test_skip_preserves_existing_target_and_source_and_tracks_mixed_batch(tmp_path):
    source = tmp_path / 'src'
    destination = tmp_path / 'dst'
    source.mkdir()
    destination.mkdir()
    (source / 'same.txt').write_text('new')
    (source / 'free.txt').write_text('free')
    (destination / 'same.txt').write_text('old')
    svc = FileSystemService(PathResolver())
    result = svc.paste_paths(
        [str(source / 'same.txt'), str(source / 'free.txt')],
        str(destination), 'move', policies=['skip', 'skip'],
    )
    assert (result.total, result.succeeded, result.skipped, result.failed, result.status) == (2, 1, 1, 0, 1)
    assert result.to_dict()['skipped'] == 1
    assert (source / 'same.txt').read_text() == 'new'
    assert (destination / 'same.txt').read_text() == 'old'
    assert (destination / 'free.txt').read_text() == 'free'
    assert not (source / 'free.txt').exists()
    repeated = svc.paste_paths([str(source / 'same.txt')], str(destination), 'move', policies=['skip'])
    assert (repeated.succeeded, repeated.skipped, repeated.failed, repeated.status) == (0, 1, 0, 1)


def test_zip_skip_leaves_existing_destination_unchanged(tmp_path):
    archive = tmp_path / 'bundle.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('root/changed.txt', 'incoming')
    target = tmp_path / 'dest'
    (target / 'root').mkdir(parents=True)
    (target / 'root' / 'changed.txt').write_text('existing')
    result = ArchiveService(PathResolver()).extract_zip_with_policy(str(archive), str(target), policy='skip')
    assert result['skipped'] is True
    assert result['file_count'] == 0
    assert (target / 'root' / 'changed.txt').read_text() == 'existing'
    assert not list(target.glob('.rch-zip-stage-*'))
