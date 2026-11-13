"""ZIP Peek entry extraction: exact selection, safe targets, and binary bytes."""
import zipfile

import pytest

from client.runtime.filesystem.archive_service import ArchiveService
from client.runtime.filesystem.path_resolver import PathResolver


def build_zip(tmp_path, entries):
    archive_path = tmp_path / 'bundle.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return archive_path


def test_select_file_full_binary_and_no_overwrite(tmp_path):
    binary = bytes(range(256)) * 12000  # Larger than the 2 MiB text preview limit.
    source = build_zip(tmp_path, {'top/a.bin': binary, 'top/b.txt': 'not selected'})
    dest = tmp_path / 'dest'
    dest.mkdir()
    service = ArchiveService(PathResolver())
    result = service.extract_zip_entry(str(source), str(dest), 'top/a.bin')
    assert result['mode'] == 'selected_entry'
    assert result['file_count'] == 1
    assert result['extracted_to'] == str(dest / 'a.bin')
    assert (dest / 'a.bin').read_bytes() == binary
    assert not (dest / 'top').exists()
    assert not (dest / 'b.txt').exists()
    with pytest.raises(FileExistsError):
        service.extract_zip_entry(str(source), str(dest), 'top/a.bin')
    assert (dest / 'a.bin').read_bytes() == binary


def test_select_implicit_directory_preserves_subtree(tmp_path):
    source = build_zip(tmp_path, {'root/group/a.txt': 'A', 'root/group/sub/b.txt': 'B', 'root/sibling.txt': 'skip'})
    dest = tmp_path / 'dest'
    dest.mkdir()
    service = ArchiveService(PathResolver())
    result = service.extract_zip_entry(str(source), str(dest), 'root/group')
    assert result['file_count'] == 2
    assert (dest / 'group/a.txt').read_text() == 'A'
    assert (dest / 'group/sub/b.txt').read_text() == 'B'
    assert not (dest / 'root').exists()
    with pytest.raises(FileExistsError):
        service.extract_zip_entry(str(source), str(dest), 'root/group')


def test_invalid_or_unsafe_entry_does_not_escape_destination(tmp_path):
    source = build_zip(tmp_path, {'safe.txt': 'SAFE', 'dir/child.txt': 'SAFE'})
    dest = tmp_path / 'dest'
    dest.mkdir()
    service = ArchiveService(PathResolver())
    for selected, error in [('no.txt', FileNotFoundError), ('../escape', ValueError), ('dir/../../escape', ValueError)]:
        with pytest.raises(error):
            service.extract_zip_entry(str(source), str(dest), selected)
    assert list(dest.iterdir()) == []
    unsafe = build_zip(tmp_path, {'../escape.txt': 'bad', 'safe.txt': 'safe'})
    with pytest.raises(ValueError):
        service.extract_zip_entry(str(unsafe), str(dest), 'safe.txt')
    assert list(dest.iterdir()) == []
