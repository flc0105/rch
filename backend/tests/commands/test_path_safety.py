"""Focused behavior tests for project module: commands."""

from pathlib import Path
import pytest
from client.runtime.sdk import path_patterns
import os
import tempfile
import unittest
from unittest.mock import patch
from client.commands.common.services.filesystem.path_resolver import PathResolver
from client.external_tools.daemon_instance import ExternalToolDaemonInstance


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


class PathResolverTildeTests(unittest.TestCase):
    def test_resolve_target_path_expands_remote_home(self):
        resolver = PathResolver()
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            expected = os.path.join(home, 'Documents', 'Typora')
            self.assertEqual(
                resolver.resolve_target_path('~/Documents/Typora'),
                os.path.abspath(expected),
            )

    def test_existing_directory_helpers_accept_tilde_paths(self):
        resolver = PathResolver()
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            target = os.path.join(home, 'Documents', 'Typora')
            os.makedirs(target)

            self.assertEqual(
                resolver.require_existing_directory_from_arg('~/Documents/Typora'),
                os.path.abspath(target),
            )
            self.assertEqual(
                resolver.validate_directory_exists('~/Documents/Typora'),
                os.path.abspath(target),
            )

    def test_external_tool_runtime_expands_tilde_argv_on_client(self):
        tool = ExternalToolDaemonInstance.__new__(ExternalToolDaemonInstance)
        tool.validate_package_payload = lambda payload, action='': ('mac', 'arm64')

        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            runtime = tool.build_runtime({
                'runtime': {
                    'argv': [
                        '/usr/bin/env',
                        'SB_USER=admin:admin',
                        '/tmp/silverbullet',
                        '--single',
                        '~/Documents/Typora',
                    ],
                    'cwd': home,
                    'stdout': os.path.join(home, 'stdout.log'),
                    'pid_file': os.path.join(home, 'tool.pid'),
                },
            })

        self.assertEqual(
            runtime['argv'][-1],
            os.path.abspath(os.path.join(home, 'Documents', 'Typora')),
        )

    def test_relative_paths_keep_current_working_directory_semantics(self):
        resolver = PathResolver()
        with tempfile.TemporaryDirectory() as cwd, patch('os.getcwd', return_value=cwd):
            self.assertEqual(
                resolver.resolve_target_path('Documents/Typora'),
                os.path.abspath(os.path.join(cwd, 'Documents', 'Typora')),
            )
