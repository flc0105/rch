"""The generated Python bootstrap must avoid all subprocess use on Pythonista/iOS."""
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService


def _generated_script():
    service = AgentBootstrapScriptService()
    return service.generate_python_script({
        'server_host': '127.0.0.1', 'server_port': 9999,
        'web_port': 8085, 'server_web_host': '127.0.0.1',
        'server_web_scheme': 'http',
    })


def test_pythonista_runtime_selects_current_python_without_subprocess(tmp_path):
    script = _generated_script()
    namespace = {'__name__': 'generated_bootstrap_test'}
    with patch.dict(sys.modules, {'appex': types.ModuleType('appex')}), \
         patch('pathlib.Path.home', return_value=tmp_path), \
         patch('subprocess.run', side_effect=AssertionError('subprocess must not run on iOS')):
        exec(compile(script, 'generated-bootstrap.py', 'exec'), namespace)
        assert namespace['IOS_PYTHONISTA'] is True
        assert namespace['ROOT'] == tmp_path / 'Documents' / 'client_bundle'
        assert namespace['prepare_python']() == sys.executable


def test_pythonista_rejects_old_interpreter_without_spawning(tmp_path):
    script = _generated_script()
    namespace = {'__name__': 'generated_bootstrap_test'}
    with patch.dict(sys.modules, {'appex': types.ModuleType('appex')}), patch('pathlib.Path.home', return_value=tmp_path):
        exec(compile(script, 'generated-bootstrap.py', 'exec'), namespace)
        namespace['MIN_PYTHON'] = (sys.version_info.major + 1, 0)
        with pytest.raises(RuntimeError, match='Python 3.10 or newer'):
            namespace['prepare_python']()


def test_desktop_still_uses_interpreter_probe():
    script = _generated_script()
    namespace = {'__name__': 'generated_bootstrap_test'}
    with patch.dict(sys.modules, {'appex': None}):
        exec(compile(script, 'generated-bootstrap.py', 'exec'), namespace)
    if sys.platform != 'ios':
        assert namespace['IOS_PYTHONISTA'] is False
        assert namespace['runtime_version'](sys.executable) >= (3, 10)


def test_ios_generated_bootstrap_installs_bundle_without_importing_subprocess(tmp_path):
    import hashlib
    import zipfile

    bundle = tmp_path / 'payload.zip'
    with zipfile.ZipFile(bundle, 'w') as archive:
        archive.writestr('rchclient.py', 'print("ready")\n')
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    namespace = {'__name__': 'generated_bootstrap_test'}
    with patch.dict(sys.modules, {'appex': types.ModuleType('appex'), 'subprocess': None}), \
         patch('pathlib.Path.home', return_value=tmp_path):
        exec(compile(_generated_script(), 'generated-bootstrap.py', 'exec'), namespace)
        launched = []
        namespace['build_bundle'] = lambda: {
            'build_version': 'ios-run', 'file_name': 'payload.zip',
            'download_url': '/api/agent/download/payload.zip', 'sha256': digest,
        }
        namespace['download'] = lambda url, dest, sha256: dest.write_bytes(bundle.read_bytes())
        namespace['launch'] = lambda python, location: launched.append((python, location))
        namespace['main']()
        expected = tmp_path / 'Documents' / 'client_bundle' / 'releases' / 'ios-run'
        assert (expected / 'rchclient.py').is_file()
        assert launched == [(sys.executable, expected)]
