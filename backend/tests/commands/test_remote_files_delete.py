"""Remote Files deletion on removable volumes: disappearing children are not fatal."""
import os
import shutil
from unittest.mock import patch

import pytest

from client.commands.common.services.filesystem.file_system_service import FileSystemService
from client.commands.common.services.filesystem.path_resolver import PathResolver


def test_disappearing_appledouble_child_does_not_fail_directory_delete(tmp_path):
    target = tmp_path / 'external-drive-folder'
    target.mkdir()
    (target / 'ordinary.txt').write_text('data')
    service = FileSystemService(PathResolver())
    real_rmtree = shutil.rmtree

    def removable_drive_rmtree(path, *, onerror=None, **kwargs):
        # Simulate an AppleDouble entry disappearing between scan and unlink.
        missing_child = os.path.join(str(path), '._.DS_Store')
        onerror(os.unlink, missing_child, (FileNotFoundError, FileNotFoundError(2, 'No such file', missing_child), None))
        return real_rmtree(path, **kwargs)

    with patch('client.commands.common.services.filesystem.file_system_service.shutil.rmtree', side_effect=removable_drive_rmtree):
        success, message = service.delete_target_path(str(target))
    assert success == 1 and 'Directory deleted:' in message
    assert not target.exists()


def test_root_missing_or_permission_error_is_not_silently_accepted(tmp_path):
    service = FileSystemService(PathResolver())
    target = str(tmp_path / 'missing')
    with pytest.raises(FileNotFoundError):
        service._delete_directory_tree(target)

    target_dir = tmp_path / 'readonly'
    target_dir.mkdir()
    def permission_denied(path, *, onerror=None):
        child = os.path.join(str(path), 'protected')
        onerror(os.unlink, child, (PermissionError, PermissionError(13, 'Permission denied', child), None))
    with patch('client.commands.common.services.filesystem.file_system_service.shutil.rmtree', side_effect=permission_denied):
        with pytest.raises(PermissionError):
            service._delete_directory_tree(str(target_dir))


def test_bulk_delete_reuses_safe_directory_removal(tmp_path):
    service = FileSystemService(PathResolver())
    parent = tmp_path / 'external'
    parent.mkdir()
    (parent / 'child.txt').write_text('content')
    result = service.delete_paths([str(parent)])
    assert result.succeeded == 1
    assert not parent.exists()
