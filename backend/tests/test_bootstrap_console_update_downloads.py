"""Bootstrap diagnostics and update archive-directory regression checks."""
import contextlib
import io
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.client_revision import BUNDLE_ARTIFACT_STEM, bundle_archive_name
from client.commands.common.mixins.update_ops import CommandUpdateMixin
from client.commands.common.services.client_cleanup_service import ClientCleanupService
from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService


class BootstrapConsoleTests(unittest.TestCase):
    def setUp(self):
        self.scripts = AgentBootstrapScriptService()
        self.params = {'server_host': 'localhost', 'server_port': 9999, 'web_port': 8085}

    def _scope(self):
        source = self.scripts.generate_python_script(self.params)
        env = {'__name__': 'bootstrap_test'}
        exec(compile(source, 'generated-bootstrap.py', 'exec'), env)
        return env

    def test_macos_describes_local_runtime_selection(self):
        env = self._scope()
        env['sys'] = types.SimpleNamespace(platform='darwin', executable='/example/py3')
        env['runtime_version'] = lambda _path: (3, 11)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            result = env['prepare_python']()
        self.assertEqual(result, '/example/py3')
        self.assertIn('Preparing Python runtime', captured.getvalue())
        self.assertIn('Checking local Python: /example/py3 (3.11)', captured.getvalue())
        self.assertIn('Using local Python: /example/py3', captured.getvalue())

    def test_windows_describes_cached_embed_or_local_choice(self):
        env = self._scope()
        env['sys'] = types.SimpleNamespace(platform='win32', executable='C:/Local/python.exe')
        env['find_embedded'] = lambda root: Path('C:/Cache/python.exe')
        env['runtime_version'] = lambda p: (3, 13) if 'Cache' in str(p) else (3, 11)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.assertEqual(str(env['prepare_python']()), 'C:/Cache/python.exe')
        self.assertIn('Using cached Python Embed', captured.getvalue())
        env['find_embedded'] = lambda root: None
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.assertEqual(str(env['prepare_python']()), 'C:/Local/python.exe')
        self.assertIn('No cached Python Embed found', captured.getvalue())
        self.assertIn('Using local Python', captured.getvalue())

    def test_windows_downloads_embed_only_after_cached_and_local_rejected(self):
        env = self._scope()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env['RUNTIME_DIR'] = root / 'runtimes' / 'python-embed'
            env['DOWNLOADS_DIR'] = root / 'downloads'
            env['sys'] = types.SimpleNamespace(
                platform='win32', executable='C:/oldpython.exe',
                getwindowsversion=lambda: types.SimpleNamespace(major=10, minor=0))
            env['find_embedded'] = lambda folder: (folder / 'python.exe') if (folder / 'python.exe').is_file() else None
            env['runtime_version'] = lambda binary: (3, 13) if 'runtimes' in str(binary) or '.part' in str(binary) else (3, 8)
            calls = []
            def fake_download(url, dest, sha256=None):
                calls.append(('download', url, dest))
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b'zip')
            def fake_extract(src, dest):
                calls.append(('extract', src, dest))
                dest.mkdir(parents=True)
                (dest / 'python.exe').write_bytes(b'python')
            env['download'] = fake_download
            env['extract_zip'] = fake_extract
            output = io.StringIO()
            with patch('platform.machine', return_value='AMD64'), \
                 patch('shutil.which', return_value=None), contextlib.redirect_stdout(output):
                runtime = env['prepare_python']()
            self.assertEqual(runtime, str(env['RUNTIME_DIR'] / 'python.exe'))
            self.assertEqual([r[0] for r in calls], ['download', 'extract'])
            self.assertIn('No compatible local Python; downloading Python Embed for win/amd64', output.getvalue())
            self.assertIn('Python Embed ready:', output.getvalue())

    def test_python_full_bootstrap_phases_present(self):
        source = self.scripts.generate_python_script(self.params)
        for snippet in ('Preparing Python runtime', 'Using local Python', 'Using cached Python Embed',
                        'downloading Python Embed', 'Requesting Bundle build', 'Bundle build ready',
                        'Downloading Bundle', 'Download SHA-256 verified', 'Extracting',
                        'Bundle installed successfully', 'Launching detached Client',
                        'handoff done, bootstrap exits'):
            self.assertIn(snippet, source)

    def test_powershell_full_bootstrap_phases_present(self):
        source = self.scripts.generate_powershell_script(self.params)
        for snippet in ('Preparing Python runtime', 'Using local Python', 'Using cached Python Embed',
                        'downloading Python Embed', 'Requesting Bundle build', 'Bundle build ready',
                        'Downloading Bundle', 'Bundle SHA-256 verified', 'Extracting Bundle',
                        'Bundle installed successfully', 'Launching detached Client',
                        'Bootstrap complete.'):
            self.assertIn(snippet, source)
        self.assertLess(source.index('Using cached Python Embed'), source.index('Using local Python'))
        self.assertIn('-WindowStyle Hidden', source)


class UpdateZipDirectoryTests(unittest.TestCase):
    def test_update_only_moves_zip_path_and_keeps_extract_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / 'releases'
            downloads_dir = Path(tmp) / 'downloads'
            release_dir.mkdir()
            command = CommandUpdateMixin()
            command._parse_update_options = lambda _args: {'keep_old': True}
            command._request_update_bundle = lambda: {'file_name': bundle_archive_name('test'),
                'download_url': '/download'}
            command._send_info = lambda *a, **k: None
            command._send_success = lambda *a, **k: None
            command._send_error = lambda *a, **k: self.fail(f'Update failed: {a}')
            paths = []
            command._download_bundle_archive = lambda url, path: paths.append(('download', path))
            command._get_current_bundle_release_dir = lambda root: str(release_dir / 'running')
            command._extract_update_bundle_safely = lambda zip_path, extract_dir, current: (
                paths.append(('extract', zip_path, extract_dir, current)) or extract_dir)
            command._build_update_ready_paths = lambda release: (str(release_dir/'ready'), str(release_dir/'error'))
            command._wait_for_updated_client_ready = lambda *a: {'client_id': 'client-1'}
            command._activate_updated_client_watchdog = lambda *a: None
            command._cleanup_update_probe_files = lambda *a: None
            class Process:
                pid = 1234
                def poll(self): return 0
            with patch('client.commands.common.mixins.update_ops.get_client_bundle_release_dir',
                       return_value=str(release_dir)), \
                 patch('client.commands.common.mixins.update_ops.get_client_bundle_download_dir',
                       return_value=str(downloads_dir)), \
                 patch('client.commands.common.mixins.update_ops.get_local_identity',
                       return_value=types.SimpleNamespace(os_alias='mac')), \
                 patch('client.commands.common.mixins.update_ops.spawn_detached_python_script',
                       return_value=Process()) as spawn:
                command.update('--keep-old')
            self.assertEqual(paths[0][1], str(downloads_dir / bundle_archive_name('test')))
            self.assertEqual(paths[1][1], paths[0][1])
            self.assertEqual(paths[1][2], str(release_dir / (BUNDLE_ARTIFACT_STEM + '-test')))
            self.assertEqual(paths[1][3], str(release_dir / 'running'))
            self.assertEqual(spawn.call_args.kwargs['cwd'], paths[1][2])

    def test_clean_zip_residue_preserves_embed_and_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / 'downloads';downloads.mkdir()
            bundle = downloads / bundle_archive_name('test');bundle.write_bytes(b'bundle')
            embed = downloads / 'python-embed.zip';embed.write_bytes(b'embed')
            other = downloads / 'my-notes.zip';other.write_bytes(b'personal')
            service = ClientCleanupService()
            with patch('client.commands.common.services.client_cleanup_service.get_client_bundle_download_dir',
                       return_value=str(downloads)):
                result = service._clean_bundle_archive_residue()
            self.assertFalse(bundle.exists())
            self.assertTrue(embed.exists())
            self.assertTrue(other.exists())
            self.assertEqual(result['removed_files'], 1)

    def test_clean_releases_keeps_running_dir_and_removes_bundle_zip_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            releases = Path(tmp) / 'releases';releases.mkdir()
            current = releases / 'running';current.mkdir();(current/'rchclient.py').write_text('pass')
            stale = releases / 'old';stale.mkdir();(stale/'rchclient.py').write_text('pass')
            downloads = Path(tmp) / 'downloads';downloads.mkdir()
            archive = downloads/bundle_archive_name('old');archive.write_bytes(b'x')
            embed = downloads/'python-embed.zip';embed.write_bytes(b'y')
            command = CommandUpdateMixin();command._checkpoint = lambda: None
            with patch('client.commands.common.mixins.update_ops.get_client_bundle_download_dir',
                       return_value=str(downloads)):
                result = command._clean_outdated_bundle_releases(str(releases), str(current))
            self.assertTrue(current.exists())
            self.assertFalse(stale.exists())
            self.assertFalse(archive.exists())
            self.assertTrue(embed.exists())
            self.assertEqual(result['deleted_zips'], [str(archive)])

if __name__ == '__main__':
    unittest.main()
