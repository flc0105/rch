import os

import pytest

pytest.importorskip("werkzeug")

from server.application.scripts.script_catalog_service import ScriptCatalogService


def test_script_rename_updates_name_and_preserves_source_and_permissions(tmp_path):
    service = ScriptCatalogService(str(tmp_path))
    source = 'SCRIPT_METADATA = {"name": "folder/old", "display_name": "Old"}\n# note\nprint("folder/old")\n'
    service.save_script('folder/old', source)
    old = tmp_path / 'folder/old.py'
    old.chmod(0o640)
    result = service.rename_script('folder/old.py', 'new/renamed.py')
    target = tmp_path / 'new/renamed.py'
    assert result['name'] == 'new/renamed'
    assert not old.exists()
    assert target.read_text() == source.replace('"name": "folder/old"', '"name": "new/renamed"')
    assert target.stat().st_mode & 0o777 == 0o640
    service.save_script('new/renamed', target.read_text().replace('new/renamed', 'other/name'))
    assert target.exists() and not (tmp_path / 'other/name.py').exists()


def test_script_rename_without_name_and_target_collision(tmp_path):
    service = ScriptCatalogService(str(tmp_path))
    service.save_script('old', 'print("hello")\n')
    service.save_script('exists', 'print("keep")\n')
    with pytest.raises(FileExistsError):
        service.rename_script('old', 'exists')
    assert service.get_script_content('old') == 'print("hello")\n'
    service.rename_script('old', 'new')
    assert service.get_script_content('new') == 'print("hello")\n'
    assert service.get_script_content('exists') == 'print("keep")\n'


def test_script_rename_replace_failure_restores_old_file(tmp_path, monkeypatch):
    service = ScriptCatalogService(str(tmp_path))
    content = 'SCRIPT_METADATA = {"name": "old"}\n'
    service.save_script('old', content)
    def fail(*args):
        raise OSError('replace failed')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='replace failed'):
        service.rename_script('old', 'new')
    assert service.get_script_content('old') == content
    assert not (tmp_path / 'new.py').exists()
    assert list(tmp_path.iterdir()) == [tmp_path / 'old.py']
