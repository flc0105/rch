"""Same-host different-port deployments cannot overwrite each other's admin cookie."""
import os
import subprocess
import sys
from pathlib import Path


def test_cookie_name_is_unique_for_each_deployment(tmp_path):
    root = Path(__file__).resolve().parents[3]
    code = r'''
import importlib, os, sys, types
fake = types.ModuleType('server.config.admin_auth')
fake.load_admin_auth = lambda path: {
    'username':'user', 'password':'unused-hash', 'api_token':'unused',
    'session_secret':'fixed-secret-for-test'
}
sys.modules['server.config.admin_auth'] = fake
from server.config import config
first = config.SESSION_COOKIE_NAME
assert first.startswith('rch_admin_session_')
os.environ['RCH_WEB_PORT'] = '8082'
config = importlib.reload(config)
second = config.SESSION_COOKIE_NAME
assert first != second
os.environ['RCH_WEB_PORT'] = '8081'
config = importlib.reload(config)
assert config.SESSION_COOKIE_NAME == first
print('COOKIE_ISOLATION_OK')
'''
    env = {**os.environ, 'PYTHONPATH': str(root/'backend'),
           'RCH_WEB_PORT': '8081', 'RCH_SERVER_RUNTIME_DIR': str(tmp_path)}
    env.pop('RCH_WEB_SESSION_COOKIE_NAME', None)
    result = subprocess.run([sys.executable, '-c', code], cwd=root,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'COOKIE_ISOLATION_OK' in result.stdout
