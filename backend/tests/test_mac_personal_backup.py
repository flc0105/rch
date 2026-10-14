import importlib.util
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from client.runtime.sdk import context, scripts
from client.runtime.sdk.context import use_script_sdk_context
from server.application.auth.script_grant_policy import ScriptGrantPolicy
from core.utils.script_metadata import read_script_metadata_from_file


SCRIPTS_DIR = Path(__file__).parents[1] / 'server' / 'resources' / 'scripts'
BACKUP_FILE = SCRIPTS_DIR / 'macos/backup/personal_mac_backup.py'


def load_backup():
    spec = importlib.util.spec_from_file_location('mac_backup_test', BACKUP_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_meta_and_script_grant():
    meta = read_script_metadata_from_file(str(BACKUP_FILE))
    assert meta['name'] == 'macos/backup/personal_mac_backup'
    assert len(meta['params']) == 7
    assert meta['api_grants'] == ['scripts:read']
    policy = ScriptGrantPolicy()
    assert policy.match_request_scope('GET', '/api/scripts/download') == 'scripts:read'
    assert policy.match_request_scope('POST', '/api/scripts/save') == ''


def test_run_script_capture_json_and_exit_status(monkeypatch):
    monkeypatch.setattr('client.http.client_api.ClientApiClient.download_text',
                        lambda _self, _path, **_kw: 'import json\nprint(json.dumps({"count": kwargs.get("x")}))')
    with use_script_sdk_context(None, {'__context__': {'script_name': 'parent',
                                                       'script_grant': {'token': 'abc'}}}):
        result = scripts.run('macos/tools/child', {'x': 9})
        assert result.ok
        assert result.json() == {'count': 9}
        assert result.stderr == ''
        with pytest.raises(ValueError):
            scripts.run('../escape')
        with pytest.raises(scripts.ScriptSdkScriptsError):
            scripts.run('parent')
    monkeypatch.setattr('client.http.client_api.ClientApiClient.download_text',
                        lambda _self, _path, **_kw: 'raise SystemExit(2)')
    with use_script_sdk_context(None, {'__context__': {'script_name': 'parent',
                                                       'script_grant': {'token': 'abc'}}}):
        result = scripts.run('other')
        assert result.returncode == 2
    with pytest.raises(scripts.ScriptSdkScriptsError):
        scripts.run('other')


def test_progress_routes_to_client():
    owner = Mock()
    with use_script_sdk_context(owner, {'__context__': {}}):
        context.progress('step 1')
        context.progress('warning', status=0)
    assert owner._send_interim_result.call_args_list[0].args == (1, 'step 1', 0)
    assert owner._send_interim_result.call_args_list[1].args == (0, 'warning', 0)


def test_backup_zip_manifest_and_skip_missing_volume(tmp_path, monkeypatch):
    module = load_backup()
    home = tmp_path / 'home'
    home.mkdir()
    (home / '.zshrc').write_text('export EXAMPLE=1\n')
    (home / '.zsh_history').write_text('pwd\n')
    typora = tmp_path / 'Typora'
    (typora / 'notes').mkdir(parents=True)
    (typora / 'notes' / 'note.md').write_text('hello')
    (typora / 'notes' / 'assets').mkdir()
    (typora / 'notes' / 'assets' / 'one.png').write_bytes(b'img')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setattr(module.platform, 'node', lambda: 'test-mac')
    printed = []
    monkeypatch.setattr(module.context, 'progress', lambda text, status=1: printed.append((text, status)))

    captured = {}
    def fake_save(path, **opts):
        captured['bytes'] = Path(path).read_bytes()
        captured['name'] = Path(path).name
        captured['opts'] = opts
        return {'artifact_id': 'art-123'}
    monkeypatch.setattr(module.artifact, 'save', fake_save)
    def fake_run(script_name, params=None):
        result = { 'common/browser/get_chromium_bookmarks': [{'name': 'x', 'url': 'https://x'}],
                   'macos/recon/brew_packages': [{'type': 'formula', 'token': 'wget'}],
                   'mac/gather/get_installed_apps': [{'name': 'Typora'}]}[script_name]
        return scripts.ScriptResult(script_name, 0, json.dumps(result))
    monkeypatch.setattr(module.scripts, 'run', fake_run)
    outcome = module.main({'typora_directory': str(typora)})
    assert outcome['uploaded'] is True
    assert captured['opts']['type'] == 'shared_files'
    assert captured['name'].startswith('mac-personal-backup_')
    with zipfile.ZipFile(io.BytesIO(captured['bytes'])) as archive:
        names = archive.namelist()
        assert len(names) == 8  # 2 shell + 3 JSON + 2 Typora + 1 manifest
        assert any('/shell/zshrc_' in x for x in names)
        assert any('/shell/zsh_history_' in x for x in names)
        assert any('/browser/chrome_bookmarks_' in x for x in names)
        assert any('/documents/typora_' in x and x.endswith('notes/note.md') for x in names)
        meta_path = next(x for x in names if '/manifest/backup_manifest_' in x)
        manifest = json.loads(archive.read(meta_path))
        assert len(manifest['files']) == 7
        assert not manifest['warnings']
    assert any('Uploaded:' in text for text, _ in printed)

    printed.clear()
    params = {flag: False for flag, _ in module.SOURCES}
    params.update(include_zshrc=True, include_typora=True, typora_directory='/Volumes/DefinitelyNotMounted/Typora')
    result = module.main(params)
    assert result['uploaded'] is True  # shell item remains
    assert any('external volume not mounted' in item for item in result['warnings'])
    assert any(status == 0 for _, status in printed)

    # Selected shell dotfiles may be symlinks to a dotfiles repository.
    (home / '.zshrc').unlink()
    (home / '.zshrc').symlink_to(home / 'real_zshrc')
    (home / 'real_zshrc').write_text('PROMPT=backup\n')
    params = {flag: False for flag, _ in module.SOURCES}
    params['include_zshrc'] = True
    outcome = module.main(params)
    assert outcome['uploaded']
    with zipfile.ZipFile(io.BytesIO(captured['bytes'])) as z:
        zshrc = next(name for name in z.namelist() if '/shell/zshrc_' in name)
        assert z.read(zshrc) == b'PROMPT=backup\n'


def test_no_selected_or_no_readable_items(tmp_path, monkeypatch):
    module = load_backup()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(module.context, 'progress', lambda *args, **kwargs: None)
    called = []
    monkeypatch.setattr(module.artifact, 'save', lambda *args, **kwargs: called.append(1))
    with pytest.raises(ValueError, match='No backup items'):
        module.main({flag: False for flag, _ in module.SOURCES})
    params = {flag: False for flag, _ in module.SOURCES}
    params['include_zshrc'] = True
    result = module.main(params)
    assert not result['uploaded']
    assert not called
