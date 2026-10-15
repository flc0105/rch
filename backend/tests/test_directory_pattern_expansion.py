"""Read-only one-level path matching for future cleanup wiring."""
from pathlib import Path

import pytest
from client.runtime.sdk import path_patterns


def test_wechat_style_single_level_directory_expansion(tmp_path, monkeypatch):
    home = tmp_path / 'flc'
    base = home / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
    for account in ('account_a', 'account_b'):
        (base / account / 'msg/file').mkdir(parents=True)
        (base / account / 'msg/file' / 'keep.txt').write_text('untouched')
    (base / 'other' / 'msg').mkdir(parents=True)
    (base / 'shortcut').symlink_to(base / 'account_a', target_is_directory=True)
    (base / 'account_a' / 'msg' / 'linkfile').symlink_to(base / 'account_b/msg/file', target_is_directory=True)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    pattern = str(base / '*' / 'msg/file/')
    assert path_patterns.expand_directory_pattern(pattern) == [
        base / 'account_a/msg/file', base / 'account_b/msg/file']
    assert (base / 'account_a/msg/file/keep.txt').read_text() == 'untouched'


@pytest.mark.parametrize('pattern', [
    '~/Library/**/msg/file', '~/Library/*/msg/*', '~/Library/*', '~/Library/a*/msg/file',
    '~/Library/../*/msg/file', '/etc/*/msg/file', '~/Library/?/msg/file',
])
def test_dangerous_or_broad_patterns_rejected(pattern):
    with pytest.raises(ValueError):
        path_patterns.expand_directory_pattern(pattern)


def test_symlinked_ancestor_not_traversed(tmp_path, monkeypatch):
    home = tmp_path / 'flc'
    home.mkdir()
    external = tmp_path / 'external'
    (external / 'account/msg/file').mkdir(parents=True)
    (home / 'Library').symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    with pytest.raises(OSError):
        path_patterns.expand_directory_pattern('~/Library/*/msg/file')
