"""Destructive-cleanup safety regression tests; all filesystem operations use temp directories."""
import ast
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'server/resources/scripts/mac/recon/personal_disk_cleanup.py'
META = ast.literal_eval(ast.parse(SCRIPT.read_text()).body[0].value)


def load(monkeypatch, home):
    progress = []
    responses = []
    approval = {'allowed': False, 'callback': None}
    sdk = types.ModuleType('client.runtime.sdk')

    def ask(message, preview, **kwargs):
        responses.append((message, preview, kwargs))
        from server.application.execution.interaction_broker import InteractionBroker
        InteractionBroker._normalize_preview(preview)
        if approval['callback']:
            approval['callback']()
        return approval['allowed']

    sdk.context = types.SimpleNamespace(
        progress=lambda message, status=1: progress.append((message, status)),
        approve_preview=ask,
    )
    monkeypatch.setitem(sys.modules, 'client', types.ModuleType('client'))
    monkeypatch.setitem(sys.modules, 'client.runtime', types.ModuleType('client.runtime'))
    monkeypatch.setitem(sys.modules, 'client.runtime.sdk', sdk)
    spec = importlib.util.spec_from_file_location('personal_disk_cleanup_test', SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script.Path, 'home', lambda: home)
    return script, progress, responses, approval


def cfg(*paths, prune=False):
    return {'cleanup_paths': [{'path': str(p), 'enabled': True} for p in paths],
            'prune_pnpm_store': prune, 'clean_npm_cache': False, 'clear_nvm_cache': False}


def test_metadata_exact_scope_and_grant():
    assert META['name'] == 'mac/recon/personal_disk_cleanup'
    assert META['platforms'] == ['macos']
    assert META['api_grants'] == ['interactions:request']
    path_param, npm_param, nvm_param, pnpm_param = META['params']
    assert path_param['type'] == 'path_list'
    assert len(path_param['default']) == 5
    paths = [x['path'] for x in path_param['default']]
    for name in ['~/SeeyonLogs', '~/NCCACHE',
                 '~/upload/files', '~/Library/ScreenRecordings']:
        assert name in paths
    assert '/Users/flc/Work/Home/seeyona9/ApacheJetspeed/logs_sy' in paths
    assert npm_param['name'] == 'clean_npm_cache' and npm_param['default'] is True
    assert nvm_param['name'] == 'clear_nvm_cache' and nvm_param['default'] is True
    assert pnpm_param['name'] == 'prune_pnpm_store' and pnpm_param['default'] is True
    assert '~/.npm/_cacache' not in paths and '~/.nvm/.cache' not in paths


def test_rejection_keeps_files_and_preview(tmp_path, monkeypatch):
    script, progress, responses, approval = load(monkeypatch, tmp_path)
    root = tmp_path / 'NCCACHE'
    (root / 'nested').mkdir(parents=True)
    (root / 'a.txt').write_text('hello')
    (root / 'nested' / 'b.txt').write_text('world')
    result = script.main(cfg(root))
    assert not result['approved']
    assert (root / 'a.txt').is_file() and (root / 'nested' / 'b.txt').is_file()
    assert responses and responses[0][1]['summary'][1]['value'] == '2'
    assert responses[0][1]['rows'][0]['item'] == str(root)
    assert 'PERMANENT' in responses[0][1]['notice']


def test_approved_clears_contents_not_root(tmp_path, monkeypatch):
    script, progress, responses, approval = load(monkeypatch, tmp_path)
    root = tmp_path / 'SeeyonLogs'
    (root / 'sub').mkdir(parents=True)
    (root / '.hidden').write_text('private')
    (root / 'sub' / 'log.txt').write_bytes(b'X' * 321)
    approval['allowed'] = True
    outcome = script.main(cfg(root))
    assert root.is_dir() and list(root.iterdir()) == []
    assert outcome['removed_files_and_links'] == 2
    assert outcome['removed_directories'] == 1
    assert outcome['logical_file_bytes'] == 328
    assert outcome['pnpm_pruned'] is None


def test_symlink_unlinked_not_followed(tmp_path, monkeypatch):
    script, _, _, approval = load(monkeypatch, tmp_path)
    root = tmp_path / 'NCCACHE'
    root.mkdir()
    external = tmp_path / 'protected'
    external.mkdir()
    (external / 'keep.txt').write_text('must keep')
    (root / 'link-to-outside').symlink_to(external, target_is_directory=True)
    (root / 'link-to-file').symlink_to(external / 'keep.txt')
    approval['allowed'] = True
    result = script.main(cfg(root))
    assert result['removed_files_and_links'] == 2
    assert (external / 'keep.txt').read_text() == 'must keep'
    assert root.exists() and not list(root.iterdir())


def test_item_changed_after_preview_is_never_removed(tmp_path, monkeypatch):
    script, progress, _, approval = load(monkeypatch, tmp_path)
    root = tmp_path / 'ScreenRecordings'
    root.mkdir()
    original = root / 'movie.mov'
    original.write_bytes(b'original')
    def change():
        original.write_bytes(b'new data + additional')
        (root / 'new.mov').write_bytes(b'added during approval')
    approval['allowed'], approval['callback'] = True, change
    result = script.main(cfg(root))
    assert original.exists() and (root / 'new.mov').exists()
    assert result['removed_files_and_links'] == 0
    assert result['errors']


def test_nested_directory_swapped_to_symlink_does_not_escape(tmp_path, monkeypatch):
    script, _, _, approval = load(monkeypatch, tmp_path)
    root = tmp_path / 'upload' / 'files'
    sub = root / 'sub'
    sub.mkdir(parents=True)
    (sub / 'file').write_text('remove?')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'file').write_text('safe')
    def swap():
        (sub / 'file').unlink()
        sub.rmdir()
        sub.symlink_to(outside, target_is_directory=True)
    approval['allowed'], approval['callback'] = True, swap
    result = script.main(cfg(root))
    assert (outside / 'file').read_text() == 'safe'
    assert sub.is_symlink()
    assert result['errors']


def test_root_replacement_aborts(tmp_path, monkeypatch):
    script, _, _, approval = load(monkeypatch, tmp_path)
    root = tmp_path / 'NCCACHE'
    root.mkdir()
    (root / 'file.txt').write_text('old')
    def replace():
        root.rename(tmp_path / 'old_dir')
        root.mkdir()
        (root / 'file.txt').write_text('new')
    approval['allowed'], approval['callback'] = True, replace
    result = script.main(cfg(root))
    assert (root / 'file.txt').read_text() == 'new'
    assert (tmp_path / 'old_dir' / 'file.txt').exists()
    assert result['removed_files_and_links'] == 0


def test_disabling_paths_and_no_action(tmp_path, monkeypatch):
    script, _, responses, _ = load(monkeypatch, tmp_path)
    root = tmp_path / 'NCCACHE'
    root.mkdir()
    assert script.main({'cleanup_paths': [{'path': str(root), 'enabled': False}],
                        'prune_pnpm_store': False, 'clean_npm_cache': False, 'clear_nvm_cache': False})['reason'] == 'no targets'
    assert not responses
    assert script.main({'cleanup_paths': [], 'prune_pnpm_store': False, 'clean_npm_cache': False, 'clear_nvm_cache': False})['reason'] == 'no targets'


def test_rejects_broad_duplicate_and_nested_targets(tmp_path, monkeypatch):
    script, _, _, _ = load(monkeypatch, tmp_path)
    a = tmp_path / 'upload'
    b = a / 'files'
    b.mkdir(parents=True)
    for roots in [(tmp_path,), (a, b), (b, a), (b, b)]:
        with pytest.raises(ValueError, match='Unsafe|overlapping'):
            script.selected_directories(cfg(*roots)) if roots != (tmp_path,) else script._safe_root(str(tmp_path))
    with pytest.raises(ValueError, match='enabled must be boolean'):
        script.selected_directories({'cleanup_paths': [{'path': str(b), 'enabled': 'false'}]})


def test_pnpm_only_prunes_only_after_approval(tmp_path, monkeypatch):
    script, _, responses, approval = load(monkeypatch, tmp_path)
    pnpm = tmp_path / 'pnpm'
    pnpm.write_text('fake binary')
    calls = []
    monkeypatch.setattr(script.shutil, 'which', lambda command: str(pnpm))
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[2] == 'path':
            return types.SimpleNamespace(stdout='/test/store\n', stderr='', returncode=0)
        return types.SimpleNamespace(stdout='Pruned unused packages\n', stderr='', returncode=0)
    monkeypatch.setattr(script.subprocess, 'run', run)
    config = {'cleanup_paths': [], 'prune_pnpm_store': True, 'clean_npm_cache': False, 'clear_nvm_cache': False}
    denied = script.main(config)
    assert not denied['approved']
    assert [argv[0][2] for argv in calls] == ['path']
    assert 'Unknown reclaimable' in responses[0][1]['rows'][0]['size']
    approval['allowed'] = True
    allowed = script.main(config)
    assert allowed['approved'] and allowed['pnpm_pruned'] is True
    assert [argv[0][2] for argv in calls] == ['path', 'path', 'prune']
    assert calls[-1][1]['stdin'] == script.subprocess.DEVNULL
    assert 'shell' not in calls[-1][1]


def test_missing_path_and_pnpm_gracefully_skipped(tmp_path, monkeypatch):
    script, progress, responses, _ = load(monkeypatch, tmp_path)
    monkeypatch.setattr(script.shutil, 'which', lambda _: None)
    result = script.main(cfg(tmp_path / 'missing', prune=True))
    assert result['reason'] == 'no actionable targets'
    assert not responses
    assert any('pnpm not found' in warning for warning in result['warnings'])


def test_plan_switches_off_unsupported_preview_fields(tmp_path, monkeypatch):
    script, _, responses, _ = load(monkeypatch, tmp_path)
    root = tmp_path / 'NCCACHE'
    root.mkdir()
    (root / 'x').write_text('x')
    script.main(cfg(root))
    assert 'switches' not in responses[0][1]
    assert set(responses[0][1]) == {'summary', 'columns', 'rows', 'details', 'notice'}


def test_npm_uses_official_command_after_approval_and_pins_cache_path(tmp_path, monkeypatch):
    script, _, responses, approval = load(monkeypatch, tmp_path)
    npm = tmp_path / 'bin' / 'npm'
    npm.parent.mkdir()
    npm.write_text('fake npm executable')
    cache = tmp_path / '.npm'
    cacache = cache / '_cacache'
    cacache.mkdir(parents=True)
    (cacache / 'cached').write_bytes(b'cache data')
    calls = []
    monkeypatch.setattr(script.shutil, 'which', lambda name: str(npm) if name == 'npm' else None)

    def run(argv, **kw):
        calls.append((argv, kw))
        if argv[1:4] == ['config', 'get', 'cache']:
            return types.SimpleNamespace(stdout=str(cache) + '\n', stderr='', returncode=0)
        assert argv == [str(npm), 'cache', 'clean', '--force', '--cache=' + str(cache)]
        assert kw['stdin'] == script.subprocess.DEVNULL
        assert 'shell' not in kw
        return types.SimpleNamespace(stdout='Cache cleaned', stderr='', returncode=0)

    monkeypatch.setattr(script.subprocess, 'run', run)
    config = cfg()
    config['clean_npm_cache'] = True
    rejected = script.main(config)
    assert rejected['reason'] == 'rejected'
    assert len(calls) == 1
    assert (cacache / 'cached').exists()
    assert responses[0][1]['rows'][0]['operation'] == 'npm cache clean --force'
    assert '10 B' in responses[0][1]['rows'][0]['size']
    approval['allowed'] = True
    accepted = script.main(config)
    assert accepted['approved'] and accepted['npm_cleaned'] is True
    assert len(calls) == 3
    assert [a[0][1] for a in calls] == ['config', 'config', 'cache']


def test_nvm_runs_as_sourced_shell_function_after_approval(tmp_path, monkeypatch):
    script, _, responses, approval = load(monkeypatch, tmp_path)
    nvm_dir = tmp_path / '.nvm'
    cache = nvm_dir / '.cache'
    cache.mkdir(parents=True)
    (cache / 'archive').write_text('download')
    (nvm_dir / 'nvm.sh').write_text('''
nvm() {
  if [ "$1" = cache ] && [ "$2" = clear ]; then
    rm -f "$NVM_DIR/.cache/archive"
    echo "Cache cleared"
  else
    return 4
  fi
}
''')
    monkeypatch.setenv('NVM_DIR', str(nvm_dir))
    monkeypatch.setattr(script.shutil, 'which', lambda name: '/bin/bash' if name == 'bash' else None)
    config = cfg()
    config['clear_nvm_cache'] = True
    assert script.main(config)['reason'] == 'rejected'
    assert (cache / 'archive').exists()
    assert responses[0][1]['rows'][0]['operation'] == 'nvm cache clear'
    approval['allowed'] = True
    result = script.main(config)
    assert result['approved'] and result['nvm_cleared'] is True
    assert not (cache / 'archive').exists()
    assert nvm_dir.is_dir() and (nvm_dir / 'nvm.sh').exists()


def test_disabled_package_commands_never_probed_or_run(tmp_path, monkeypatch):
    script, _, _, approval = load(monkeypatch, tmp_path)
    root = tmp_path / 'logs'
    root.mkdir()
    (root / 'old.log').write_text('old')
    approval['allowed'] = True
    monkeypatch.setattr(script.shutil, 'which', lambda _: (_ for _ in ()).throw(
        AssertionError('No package manager should be queried')))
    result = script.main(cfg(root))
    assert result['approved'] and result['npm_cleaned'] is None
    assert result['nvm_cleared'] is None and result['pnpm_pruned'] is None
    assert not list(root.iterdir())


def test_invalid_command_toggles_cannot_bypass_validation(tmp_path, monkeypatch):
    script, _, _, _ = load(monkeypatch, tmp_path)
    for key in ('clean_npm_cache', 'clear_nvm_cache', 'prune_pnpm_store'):
        config = cfg()
        config[key] = 'true'
        with pytest.raises(ValueError, match=key):
            script.main(config)


def test_missing_managers_skip_without_approval(tmp_path, monkeypatch):
    script, _, responses, _ = load(monkeypatch, tmp_path)
    monkeypatch.setattr(script.shutil, 'which', lambda _: None)
    config = cfg()
    config.update(clean_npm_cache=True, clear_nvm_cache=True, prune_pnpm_store=True)
    result = script.main(config)
    assert result['reason'] == 'no actionable targets'
    assert not responses
    assert any('npm not found' in x for x in result['warnings'])
    assert any('nvm cleanup skipped' in x for x in result['warnings'])
    assert any('pnpm not found' in x for x in result['warnings'])


def test_package_executable_modified_after_preview_not_executed(tmp_path, monkeypatch):
    script, _, _, approval = load(monkeypatch, tmp_path)
    npm = tmp_path / 'npm'
    npm.write_text('v1')
    cache = tmp_path / '.npm'
    cache.mkdir()
    calls = []
    monkeypatch.setattr(script.shutil, 'which', lambda name: str(npm) if name == 'npm' else None)

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1:4] == ['config', 'get', 'cache']:
            return types.SimpleNamespace(stdout=str(cache) + '\n', stderr='', returncode=0)
        raise AssertionError('Never run changed npm executable')

    monkeypatch.setattr(script.subprocess, 'run', run)
    approval['allowed'] = True
    approval['callback'] = lambda: npm.write_text('changed after preview')
    config = cfg()
    config['clean_npm_cache'] = True
    result = script.main(config)
    assert result['approved'] and result['npm_cleaned'] is False
    assert len(calls) == 1


def test_old_package_cache_rows_cannot_delete_directly(tmp_path, monkeypatch):
    script, _, _, _ = load(monkeypatch, tmp_path)
    for old_cache in (tmp_path / '.npm' / '_cacache',
                      tmp_path / '.nvm' / '.cache'):
        old_cache.mkdir(parents=True)
        with pytest.raises(ValueError, match='must use npm/nvm command'):
            script.selected_directories(cfg(old_cache))
        with pytest.raises(ValueError, match='must use npm/nvm command'):
            script.selected_directories(cfg(old_cache / 'a'))
