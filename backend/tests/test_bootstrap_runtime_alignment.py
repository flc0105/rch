"""Contract tests for generated Python/PowerShell bootstrap and bundle integrity."""
import ast
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.client_revision import BUNDLE_ARTIFACT_STEM, bundle_archive_name
from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService


class BootstrapRuntimeAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.service = AgentBootstrapScriptService()
        self.payload = {'server_host': '127.0.0.1', 'server_port': 9999, 'web_port': 8085}

    def test_generated_python_script_uses_standard_runtime_contract(self):
        script = self.service.generate_python_script(self.payload)
        ast.parse(script)
        self.assertIn("MIN_PYTHON = (3, 10)", script)
        self.assertIn("ROOT = Path.home() / 'client_bundle'", script)
        self.assertIn("'runtimes' / 'python-embed'", script)
        self.assertIn("'downloads'", script)
        self.assertIn("'releases'", script)
        self.assertIn('digest.hexdigest().lower() != sha256.lower()', script)
        self.assertIn("shutil.rmtree(release)", script)
        self.assertIn("'start_new_session'", script)

    def test_macos_selects_eligible_local_python_without_embed(self):
        source = self.service.generate_python_script(self.payload)
        scope = {'__name__': 'bootstrap_test'}
        exec(compile(source, 'generated.py', 'exec'), scope)
        import types
        scope['sys'] = types.SimpleNamespace(platform='darwin', executable='/bin/python3.9')
        with patch('shutil.which', side_effect=lambda name: '/bin/python3.11' if name == 'python3' else None):
            scope['runtime_version'] = lambda name: (3, 9) if name == '/bin/python3.9' else (3, 11)
            self.assertEqual(scope['prepare_python'](), '/bin/python3.11')
            scope['runtime_version'] = lambda name: (3, 9)
            with self.assertRaisesRegex(RuntimeError, '3.10'):
                scope['prepare_python']()

    def test_generated_powershell_script_uses_same_contract(self):
        script = self.service.generate_powershell_script(self.payload)
        for expected in (
            'runtimes\\python-embed', 'downloads', 'releases',
            'function Test-Python', 'Get-Hash256', 'SHA-256 mismatch',
            'Remove-Item $release -Recurse -Force', '-WindowStyle Hidden',
            'platform=win&arch=$arch',
        ):
            self.assertIn(expected, script)
        self.assertLess(script.index('$py = Find-Embed $runtimeDir'), script.index("@('python','python3')"))
        self.assertLess(script.index("@('python','python3')"), script.index('python-embed/download?platform=win'))

    def test_python_bootstrap_installs_bundle_and_replaces_existing_release(self):
        source = self.service.generate_python_script(self.payload)
        scope = {'__name__': 'bootstrap_test'}
        exec(compile(source, 'bootstrap_generated.py', 'exec'), scope)
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            scope['ROOT'] = root_path
            scope['RUNTIME_DIR'] = root_path / 'runtimes' / 'python-embed'
            scope['DOWNLOADS_DIR'] = root_path / 'downloads'
            scope['RELEASES_DIR'] = root_path / 'releases'
            release = scope['RELEASES_DIR'] / (BUNDLE_ARTIFACT_STEM + '-test')
            release.mkdir(parents=True)
            (release / 'old.txt').write_text('old')
            zip_body = io.BytesIO()
            with zipfile.ZipFile(zip_body, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('rchclient.py', 'print("OK")\n')
                z.writestr('client/stub.py', 'PASS = True\n')
            binary = zip_body.getvalue()
            response = {'code': 0, 'data': {
                'file_name': bundle_archive_name('test'), 'download_url': '/api/agent/download/' + bundle_archive_name('test'),
                'build_version': BUNDLE_ARTIFACT_STEM + '-test', 'sha256': hashlib.sha256(binary).hexdigest()}}
            class Response(io.BytesIO):
                def __enter__(self): return self
                def __exit__(self, *args): self.close()
            def fake_urlopen(request, timeout=300):
                url = getattr(request, 'full_url', request)
                return Response(json.dumps(response).encode() if str(url).endswith('/api/agent/build') else binary)
            launched = []
            scope['runtime_version'] = lambda python: (3, 13)
            with patch('urllib.request.urlopen', side_effect=fake_urlopen), \
                 patch('subprocess.Popen', side_effect=lambda *args, **kwargs: launched.append((args, kwargs))):
                scope['main']()
            self.assertFalse((release / 'old.txt').exists())
            self.assertTrue((release / 'rchclient.py').exists())
            self.assertTrue((release / 'client/stub.py').exists())
            self.assertTrue(launched)
            self.assertEqual(launched[0][1]['cwd'], str(release))
            self.assertTrue(launched[0][1]['start_new_session'])
            self.assertEqual((root_path / 'downloads' / bundle_archive_name('test')).read_bytes(), binary)

    def test_python_bootstrap_rejects_unsafe_release_name(self):
        import types
        scope = {'__name__': 'bootstrap_test'}
        exec(compile(self.service.generate_python_script(self.payload), 'generated.py', 'exec'), scope)
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            scope['DOWNLOADS_DIR'] = root_path / 'downloads'
            scope['RELEASES_DIR'] = root_path / 'releases'
            scope['runtime_version'] = lambda executable: (3, 13)
            scope['build_bundle'] = lambda: {'file_name': 'bundle.zip', 'build_version': '..',
                'download_url': '/download', 'sha256': '0' * 64}
            with self.assertRaisesRegex(ValueError, 'Invalid build metadata path'):
                scope['main']()
            self.assertFalse((root_path / 'downloads' / 'bundle.zip').exists())

    def test_python_bootstrap_rejects_corrupt_download_without_touching_release(self):
        scope = {'__name__': 'bootstrap_test'}
        exec(compile(self.service.generate_python_script(self.payload), 'generated.py', 'exec'), scope)
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            scope['DOWNLOADS_DIR'] = root_path / 'downloads'
            scope['RELEASES_DIR'] = root_path / 'releases'
            release = scope['RELEASES_DIR'] / 'build-1'
            release.mkdir(parents=True)
            (release / 'keep.txt').write_text('existing')
            response = {'code': 0, 'data': {'build_version': 'build-1',
                        'file_name': 'bundle.zip', 'download_url': '/download', 'sha256': '0'*64}}
            class Response(io.BytesIO):
                def __enter__(self): return self
                def __exit__(self, *args): self.close()
            def fake_urlopen(request, timeout=300):
                url = getattr(request, 'full_url', request)
                return Response(json.dumps(response).encode() if str(url).endswith('/api/agent/build') else b'bad')
            with patch('urllib.request.urlopen', side_effect=fake_urlopen):
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    scope['main']()
            self.assertEqual((release / 'keep.txt').read_text(), 'existing')


if __name__ == '__main__':
    unittest.main()
