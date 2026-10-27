import json
import contextlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from core.external_tools.meta import normalize_meta
from core.external_tools.selector import select_package_key
from core.metadata.parameters import normalize_param_specs
from core.utils.job_metadata import read_job_metadata_from_file
from core.utils.script_metadata import read_script_metadata_from_file


BACKEND_ROOT = Path(__file__).resolve().parents[2]
RESOURCES = BACKEND_ROOT / 'server' / 'resources'


def test_keychain_picker_schema_normalizes_login_pair_and_secret_value():
    specs = normalize_param_specs([
        {'name': 'username', 'type': 'string'},
        {
            'name': 'password',
            'type': 'password',
            'keychain_picker': {
                'kind': 'login',
                'bindings': {'username': 'username', 'secret_value': 'password'},
            },
        },
        {
            'name': 'api_token',
            'type': 'password',
            'keychain_picker': {'kind': 'secret', 'bindings': {'secret_value': 'api_token'}},
        },
    ])
    assert specs[1]['keychain_picker'] == {
        'kind': 'login', 'bindings': {'username': 'username', 'secret_value': 'password'}
    }
    assert specs[2]['keychain_picker'] == {
        'kind': 'secret', 'bindings': {'secret_value': 'api_token'}
    }


@pytest.mark.parametrize('param', [
    {'name': 'token', 'type': 'string', 'keychain_picker': {'kind': 'secret', 'bindings': {'secret_value': 'token'}}},
    {'name': 'token', 'type': 'password', 'keychain_picker': {'kind': 'invalid', 'bindings': {'secret_value': 'token'}}},
    {'name': 'token', 'type': 'password', 'keychain_picker': {'kind': 'secret', 'bindings': {'username': 'user', 'secret_value': 'token'}}},
    {'name': 'token', 'type': 'password', 'keychain_picker': {'kind': 'secret', 'bindings': {'secret_value': 'token', 'username': 'token'}}},
    {'name': 'token', 'type': 'password', 'keychain_picker': {'kind': 'secret', 'bindings': {'secret_value': 'token', 'unknown': 'other'}}},
])
def test_invalid_keychain_picker_schema_is_rejected(param):
    with pytest.raises(ValueError):
        normalize_param_specs([param])


def test_script_and_job_examples_expose_keychain_picker_metadata():
    script = read_script_metadata_from_file(
        str(RESOURCES / 'scripts' / 'examples' / 'keychain_login_picker.py')
    )
    job = read_job_metadata_from_file(
        str(RESOURCES / 'jobs' / 'examples' / 'keychain_secret_picker.py')
    )
    assert script['params'][1]['keychain_picker']['kind'] == 'login'
    assert script['params'][1]['keychain_picker']['bindings']['username'] == 'username'
    assert job['params'][0]['keychain_picker'] == {
        'kind': 'secret', 'bindings': {'secret_value': 'password'}
    }

    script_path = RESOURCES / 'scripts' / 'examples' / 'keychain_login_picker.py'
    namespace = {'kwargs': {'username': 'demo-user', 'password': 'demo-password'}}
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(script_path.read_text(encoding='utf-8'), str(script_path), 'exec'), namespace)
    assert 'Username provided: yes' in output.getvalue()
    assert 'Password length: 13' in output.getvalue()
    assert 'demo-password' not in output.getvalue()

    from client.jobs.core.job import Job

    job_path = RESOURCES / 'jobs' / 'examples' / 'keychain_secret_picker.py'
    job_namespace = {'__name__': 'keychain_secret_picker_test'}
    exec(compile(job_path.read_text(encoding='utf-8'), str(job_path), 'exec'), job_namespace)
    job = object.__new__(job_namespace['KeychainSecretPickerJob'])
    job.job_params = {'password': 'demo-secret-value'}
    messages = []
    job.mark_running = lambda: None
    job.mark_stopped = lambda: None
    job.send_to_server = lambda status, message: messages.append((status, message))
    assert issubclass(job_namespace['KeychainSecretPickerJob'], Job)
    job.run()
    assert messages and 'present=yes' in messages[0][1]
    assert 'length=17' in messages[0][1]
    assert 'demo-secret-value' not in messages[0][1]


def test_external_tool_bundle_meta_and_archive_are_valid():
    meta_path = RESOURCES / 'external_tools' / 'metas' / 'keychain-picker-demo.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    normalized = normalize_meta(meta, path=str(meta_path))
    assert select_package_key(normalized, platform_alias='mac', arch='arm64') == 'common-all'
    assert select_package_key(normalized, platform_alias='win', arch='amd64') == 'common-all'
    module = normalized['modules'][0]
    assert module['params'][0]['keychain_picker']['kind'] == 'secret'
    assert module['params'][0]['keychain_picker']['bindings']['secret_value'] == 'api_token'

    archive_path = RESOURCES / 'external_tools' / 'packages' / 'keychain-picker-demo-v1.0.0-common-all.zip'
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert 'app.py' in archive.namelist()
        source = archive.read('app.py').decode('utf-8')
        compile(source, 'app.py', 'exec')
        completed = subprocess.run(
            [sys.executable, '-c', source, 'demo-token-value'],
            capture_output=True,
            text=True,
            check=True,
        )
    output = json.loads(completed.stdout)
    assert output == {'ok': True, 'api_token_received': True, 'api_token_length': len('demo-token-value')}
    assert 'demo-token-value' not in completed.stdout
