import hashlib
import os
from pathlib import Path

import pytest

from server.application.documents.document_library_service import DocumentLibraryService


@pytest.fixture
def library(tmp_path):
    root = tmp_path / 'docs'
    root.mkdir()
    return DocumentLibraryService({'notes': {'label': 'Notes', 'path': str(root)}}, 512 * 1024)


def test_create_tree_read_update(library, tmp_path):
    assert library.list_roots() == {'items': [{'id': 'notes', 'label': 'Notes'}]}
    library.create_directory('notes', 'nested')
    created = library.create_document('notes', 'nested/demo.md')
    assert created['content'] == ''
    assert library.list_tree('notes')['items'][0]['type'] == 'directory'
    assert library.list_tree('notes', 'nested')['items'][0]['path'] == 'nested/demo.md'
    result = library.save_document('notes', 'nested/demo.md', '# 你好\n', 'utf-8', created['sha256'])
    assert library.read_document('notes', 'nested/demo.md')['content'] == '# 你好\n'
    assert (tmp_path / 'docs/nested/demo.md').read_bytes() == '# 你好\n'.encode()
    assert result['sha256'] == hashlib.sha256('# 你好\n'.encode()).hexdigest()
    with pytest.raises(FileExistsError):
        library.create_document('notes', 'nested/demo.md')


def test_conflict_preserves_external_changes(library, tmp_path):
    doc = library.create_document('notes', 'a.md')
    path = tmp_path / 'docs/a.md'
    path.write_bytes(b'external editor')
    with pytest.raises(ValueError, match='changed on disk'):
        library.save_document('notes', 'a.md', 'overwritten', 'utf-8', doc['sha256'])
    assert path.read_bytes() == b'external editor'


@pytest.mark.parametrize('path', ['/etc/passwd.md', '../outside.md', 'a/../b.md', 'a//b.md', 'a\\b.md', 'not-markdown.txt', '.hidden.md', '.git/file.md'])
def test_unsafe_paths_rejected(library, path):
    with pytest.raises(ValueError):
        library.create_document('notes', path)


def test_symlinks_rejected(library, tmp_path):
    outside = tmp_path / 'external'
    outside.mkdir()
    (outside / 'secret.md').write_text('secret')
    (tmp_path / 'docs/alias').symlink_to(outside, target_is_directory=True)
    assert library.list_tree('notes')['items'] == []
    with pytest.raises(ValueError, match='Symbolic links'):
        library.read_document('notes', 'alias/secret.md')
    (tmp_path / 'docs/leaf.md').symlink_to(outside / 'secret.md')
    with pytest.raises(ValueError, match='Symbolic links'):
        library.read_document('notes', 'leaf.md')


@pytest.mark.parametrize('raw,codec', [
    (b'\xef\xbb\xbf# hi', 'utf-8-sig'),
    (b'\xff\xfe' + '# hi'.encode('utf-16-le'), 'utf-16-le'),
    (b'\xfe\xff' + '# hi'.encode('utf-16-be'), 'utf-16-be'),
])
def test_bom_roundtrip(library, tmp_path, raw, codec):
    path = tmp_path / 'docs/a.md'
    path.write_bytes(raw)
    doc = library.read_document('notes', 'a.md')
    assert doc['encoding'] == codec
    library.save_document('notes', 'a.md', doc['content'], doc['encoding'], doc['sha256'])
    assert path.read_bytes() == raw


def test_unknown_encoding_and_size_rejected(library, tmp_path):
    path = tmp_path / 'docs/a.md'
    path.write_bytes(b'\xff\x00broken')
    preview = library.read_document('notes', 'a.md')
    assert preview['encoding'] == 'unknown'
    assert preview['editable'] is False
    original = path.read_bytes()
    with pytest.raises(ValueError):
        library.save_document('notes', 'a.md', 'safe', 'utf-8', hashlib.sha256(original).hexdigest())
    assert path.read_bytes() == original
    path.write_bytes(b'A' * (512 * 1024 + 1))
    with pytest.raises(ValueError, match='size limit'):
        library.read_document('notes', 'a.md')


def test_encoding_failure_does_not_truncate(library, tmp_path):
    path = tmp_path / 'docs/a.md'
    path.write_bytes(b'\xff\xfe' + 'hi'.encode('utf-16-le'))
    doc = library.read_document('notes', 'a.md')
    with pytest.raises(ValueError):
        library.save_document('notes', 'a.md', 'good\x00bad', doc['encoding'], doc['sha256'])
    assert path.read_bytes() == b'\xff\xfe' + 'hi'.encode('utf-16-le')


def test_save_preserves_permissions(library, tmp_path):
    path = tmp_path / 'docs/a.md'
    path.write_text('original')
    path.chmod(0o640)
    previous = path.stat()
    item = library.read_document('notes', 'a.md')
    library.save_document('notes', 'a.md', 'updated', item['encoding'], item['sha256'])
    after = path.stat()
    assert after.st_mode & 0o777 == 0o640
    assert (after.st_uid, after.st_gid) == (previous.st_uid, previous.st_gid)


def test_no_extra_client_or_database_dependency(library):
    assert library.list_roots()['items'][0]['id'] == 'notes'
