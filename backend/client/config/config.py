import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.dirname(BASE_DIR)

PROFILE_DIR = os.path.join(BASE_DIR, 'profiles')

DEFAULT_CONFIG = {
    'server_host': '127.0.0.1',
    'server_port': 9999,
    'server_web_scheme': 'http',
    'server_web_host': '127.0.0.1',
    'server_web_port': 8085,
    'client_build_version': 'dev',
}


def _get_profile_name():
    argv = sys.argv[1:]
    for index, arg in enumerate(argv):
        if arg == '--profile' and index + 1 < len(argv):
            return argv[index + 1].strip()
        if arg.startswith('--profile='):
            return arg.split('=', 1)[1].strip()
    return 'dev'


def _load_profile_overrides(profile_name: str) -> dict:
    profile_path = os.path.join(PROFILE_DIR, f'{profile_name}.json')
    if not os.path.isfile(profile_path):
        raise FileNotFoundError(f'Config profile not found: {profile_path}')

    with open(profile_path, 'r', encoding='utf-8') as file_obj:
        data = json.load(file_obj)

    if not isinstance(data, dict):
        raise ValueError(f'Invalid config profile: {profile_path}')

    return data


def _build_runtime_config() -> dict:
    profile_name = _get_profile_name()
    config = dict(DEFAULT_CONFIG)
    config.update(_load_profile_overrides(profile_name))
    config['profile_name'] = profile_name
    return config


RUNTIME_CONFIG = _build_runtime_config()

SERVER_HOST = RUNTIME_CONFIG['server_host']
SERVER_PORT = RUNTIME_CONFIG['server_port']
SERVER_ADDR = (SERVER_HOST, SERVER_PORT)

SERVER_WEB_SCHEME = RUNTIME_CONFIG['server_web_scheme']
SERVER_WEB_HOST = RUNTIME_CONFIG['server_web_host']
SERVER_WEB_PORT = RUNTIME_CONFIG['server_web_port']
SERVER_FILE_TRANSFER_PORT = int(SERVER_WEB_PORT) + 1
UPLOAD_BASE_URL = f'{SERVER_WEB_SCHEME}://{SERVER_WEB_HOST}:{SERVER_WEB_PORT}'
FILE_TRANSFER_BASE_URL = f'{SERVER_WEB_SCHEME}://{SERVER_WEB_HOST}:{SERVER_FILE_TRANSFER_PORT}'

CLIENT_BUILD_VERSION = str(RUNTIME_CONFIG.get('client_build_version') or 'dev').strip() or 'dev'
CLIENT_SOURCE_REVISION = ''
CLIENT_SOURCE_REVISION_PARTS = {}
CLIENT_SOURCE_REVISION_FILES = {}