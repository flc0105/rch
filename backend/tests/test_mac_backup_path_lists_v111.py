import ast
import importlib.util
import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'server/resources/scripts/mac/recon/personal_mac_backup.py'
meta_tree = ast.parse(SCRIPT.read_text())
META = ast.literal_eval(meta_tree.body[0].value)


def load_backup(monkeypatch):
    uploads, progress, invocations = [], [], []
    sdk = types.ModuleType('client.runtime.sdk')

    def save(path, **kw):
        assert kw['type'] == 'shared_files' and kw['category'] == 'script'
        with zipfile.ZipFile(path) as z:
            uploads.append({name: z.read(name) for name in z.namelist()})
        return {'artifact_id': 'fake-upload'}

    def run(name, params):
        invocations.append((name, params))
        return types.SimpleNamespace(ok=True, stdout='[]', stderr='', json=lambda: [])

    sdk.artifact = types.SimpleNamespace(save=save)
    sdk.context = types.SimpleNamespace(progress=lambda message, status=1: progress.append((message, status)))
    sdk.scripts = types.SimpleNamespace(run=run)
    monkeypatch.setitem(sys.modules, 'client', types.ModuleType('client'))
    monkeypatch.setitem(sys.modules, 'client.runtime', types.ModuleType('client.runtime'))
    monkeypatch.setitem(sys.modules, 'client.runtime.sdk', sdk)
    spec = importlib.util.spec_from_file_location('personal_backup_new', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, uploads, progress, invocations


def none_selected():
    return {p['name']: False for p in META['params'] if p['type'] == 'boolean'} | {'documents': [], 'projects': []}


def put(root, rel, value='x'):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value)
    return p


def test_meta_five_flags_and_two_path_list_defaults():
    assert META['name'] == 'mac/recon/personal_mac_backup'
    assert [p['name'] for p in META['params']] == [
        'include_zshrc', 'include_zsh_history', 'include_chrome_bookmarks',
        'include_homebrew', 'include_installed_apps', 'documents', 'projects',
    ]
    docs, projects = META['params'][-2:]
    assert docs['type'] == projects['type'] == 'path_list'
    assert docs['default'] == [{'path': '/Users/flc/Documents/Typora', 'enabled': True}]
    assert [x['path'] for x in projects['default']] == [
        '/Users/flc/PycharmProjects/rch', '/Volumes/T7/Projects/photo_library',
        '/Users/flc/Projects/oh-my-wechat-personal',
    ]


def test_filters_document_and_project_are_different(monkeypatch):
    backup, uploads, progress, invocations = load_backup(monkeypatch)
    assert backup.PROJECT_EXCLUDED_DIRS == frozenset({
        'venv', 'virtualenv', '__pycache__', 'site-packages', 'node_modules',
        'dist', 'tmp', 'temp', 'logs',
    })
    for name in ('notes.out', 'trace.log', 'build/report.txt', 'coverage/detail.json', 'uploads/blob.bin'):
        assert backup.excluded_entry(name, directory=False, project=False) is False
    for name in ('.secret', '.idea', '._resource', '__MACOSX'):
        assert backup.excluded_entry(name, directory=False, project=False)
    assert backup.excluded_entry('trace.out', directory=False, project=True)
    assert not backup.excluded_entry('build', directory=True, project=True)
    assert backup.excluded_entry('venv', directory=True, project=True)


def test_zip_includes_enabled_only_with_same_basename_and_keeps_build(tmp_path, monkeypatch):
    backup, uploads, progress, invocations = load_backup(monkeypatch)
    docs = tmp_path / 'docs' / 'Notes'
    proj1 = tmp_path / 'A' / 'rch'
    proj2 = tmp_path / 'B' / 'rch'
    inactive = tmp_path / 'disabled'
    for root in (docs, proj1, proj2, inactive):
        put(root, 'root.md')
        put(root, '.git/config')
        put(root, '._apple')
        put(root, '__MACOSX/fork')
        put(root, 'build/built.txt')
        put(root, 'coverage/index.html')
        put(root, 'venv/code.py')
        put(root, 'node_modules/pkg.js')
        put(root, 'out.out')
    params = none_selected()
    params['documents'] = [{'path': str(docs), 'enabled': True}, {'path': str(inactive), 'enabled': False}]
    params['projects'] = [{'path': str(proj1), 'enabled': True}, {'path': str(proj2), 'enabled': True}]
    result = backup.main(params)
    assert result['uploaded'] and len(uploads) == 1
    names = list(uploads[0])
    date = backup.datetime.now().astimezone().strftime('%Y-%m-%d')
    for p in (f'documents/notes_{date}', f'projects/rch_{date}', f'projects/rch_2_{date}'):
        assert any(x.endswith(p+'/root.md') for x in names)
    assert any('/documents/notes_' in x and x.endswith('/venv/code.py') for x in names)
    assert any('/documents/notes_' in x and x.endswith('/out.out') for x in names)
    assert not any('/projects/' in x and '/venv/' in x for x in names)
    assert not any('/projects/' in x and '/out.out' in x for x in names)
    assert any('/projects/' in x and x.endswith('/build/built.txt') for x in names)
    assert any('/projects/' in x and x.endswith('/coverage/index.html') for x in names)
    assert not any('/disabled/' in x or '/.git/' in x or '/__MACOSX/' in x or '/._apple' in x for x in names)
    assert all(item['enabled'] for item in params['projects'])
    assert result['counts']['projects_rch']['files'] > 0
    assert result['counts']['projects_rch_2']['files'] > 0
    assert any('completed documents_notes' in p[0] for p in progress)
    manifest = next(json.loads(v) for k,v in uploads[0].items() if '/manifest/' in k)
    assert manifest['counts'] == result['counts']
    assert len(manifest['files']) == sum(g['files'] for g in manifest['counts'].values())


def test_missing_external_volume_warns_but_uploads_other_items(tmp_path, monkeypatch):
    backup, uploads, progress, invocations = load_backup(monkeypatch)
    docs = tmp_path / 'notes'
    put(docs, 'readme.md')
    monkeypatch.setattr(backup.os.path, 'ismount', lambda p: False)
    params = none_selected()
    params['documents'] = [{'path': str(docs), 'enabled': True}]
    params['projects'] = [{'path': '/Volumes/T7/Projects/photo_library', 'enabled': True}]
    result = backup.main(params)
    assert result['uploaded'] and uploads
    assert any('external volume not mounted' in w for w in result['warnings'])


def test_all_rows_deleted_do_not_default_back(monkeypatch):
    backup, uploads, _, _ = load_backup(monkeypatch)
    with pytest.raises(ValueError, match='No backup items selected'):
        backup.main(none_selected())
    params = none_selected()
    params['documents'] = [{'path': '/nonexistent', 'enabled': False}]
    with pytest.raises(ValueError, match='No backup items selected'):
        backup.main(params)
    assert not uploads


def test_settings_collectors_unchanged(monkeypatch):
    backup, uploads, _, invocations = load_backup(monkeypatch)
    params = none_selected()
    params.update(include_chrome_bookmarks=True, include_homebrew=True, include_installed_apps=True)
    assert backup.main(params)['uploaded']
    assert [i[0] for i in invocations] == [
        'common/browser/get_chromium_bookmarks',
        'mac/recon/backup_brew_packages', 'mac/recon/backup_installed_apps',
    ]


def test_backend_path_list_resolution_keeps_disabled_and_empty(monkeypatch):
    sys.path.insert(0, str(ROOT))
    from core.utils.script_metadata import resolve_script_params
    incoming = [{'path': ' /tmp/project ', 'enabled': False}, {'path': '/tmp/other', 'enabled': True}]
    data = resolve_script_params(META, {'documents': [], 'projects': incoming})
    assert data['documents'] == []
    assert data['projects'] == [{'path': '/tmp/project', 'enabled': False}, {'path': '/tmp/other', 'enabled': True}]
    defaults = resolve_script_params(META, {})
    assert defaults['documents'][0]['path'].endswith('/Typora')
    with pytest.raises(ValueError, match='Invalid editable path list'):
        resolve_script_params(META, {'projects': '/tmp/rch'})
    with pytest.raises(ValueError, match='Invalid path row'):
        resolve_script_params(META, {'projects': [{'other': 'bad'}]})
    with pytest.raises(ValueError, match='Invalid enabled flag'):
        resolve_script_params(META, {'projects': [{'path': '/tmp', 'enabled': 'false'}]})
