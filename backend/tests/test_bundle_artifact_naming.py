"""Canonical Bundle name must agree across build metadata, ZIP and Client Update."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.client_revision import BUNDLE_ARTIFACT_STEM, bundle_archive_name, is_bundle_archive
from client.runtime.client_util import build_bundle_extract_dir
from server.application.agent.agent_builder import AGENT_BUILDERS, AgentBuilder


def test_bundle_naming_has_one_canonical_stem():
    assert AGENT_BUILDERS['bundle'][2] == BUNDLE_ARTIFACT_STEM
    assert bundle_archive_name('sample') == f'{BUNDLE_ARTIFACT_STEM}-sample.zip'
    assert is_bundle_archive(bundle_archive_name('sample'))
    assert not is_bundle_archive('python-embed.zip')
    assert not is_bundle_archive('unrelated-bundle.zip')
    assert not is_bundle_archive(f'{BUNDLE_ARTIFACT_STEM}-sample.txt')


def test_real_bundle_zip_version_matches_both_installers():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / 'client' / 'config').mkdir(parents=True)
        (root / 'client' / 'config' / 'config.py').write_text('old')
        (root / 'core').mkdir()
        (root / 'core' / 'core.py').write_text('some code')
        (root / 'rchclient.py').write_text('print("ok")')
        builder = AgentBuilder.__new__(AgentBuilder)
        builder.source_dir = str(root)
        builder.output_dir = str(root / 'out')
        builder._ensure_dirs()
        with patch('server.application.agent.agent_build_utils.build_client_revision_manifest',
                   return_value={'revision': 'abc', 'parts': {}, 'files': {}}):
            artifact = builder.build_agent('127.0.0.1', 9999, 8085, builder='bundle')
        version = artifact['build_version']
        assert version == f'{BUNDLE_ARTIFACT_STEM}-{version[len(BUNDLE_ARTIFACT_STEM) + 1:]}'
        assert artifact['file_name'] == version + '.zip'
        assert build_bundle_extract_dir(str(root / 'releases'), artifact['file_name']) == str(root / 'releases' / version)
        assert (root / 'out' / artifact['file_name']).is_file()
