import json
import os
import tempfile

from client.runtime.temp_workspace import register_temp_path, release_temp_path, cleanup_temp_path
from core.platform.platform_identity import detect_platform_alias


CONFIG_ENV_NAME = 'RUNTIME_CONFIG_PATH'
CONFIG_FILE_NAME = 'runtime_config.json'
APP_DIR_NAME = 'rchclient'


def get_runtime_config_path() -> str:
    """
    返回 runtime 配置覆盖文件路径。

    注意：
    - 这里永远不返回 client/config/runtime_config.py
    - 打包后也只写外部可写目录
    - 可用 RUNTIME_CONFIG_PATH 显式覆盖
    """
    override_path = os.environ.get(CONFIG_ENV_NAME, '').strip()
    if override_path:
        return os.path.abspath(os.path.expanduser(override_path))

    return os.path.join(get_runtime_config_dir(), CONFIG_FILE_NAME)


def get_runtime_config_dir() -> str:
    platform_alias = detect_platform_alias()
    if platform_alias == 'win':
        base_dir = os.environ.get('APPDATA', '').strip()
        if not base_dir:
            base_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
        return os.path.join(base_dir, APP_DIR_NAME)

    if platform_alias == 'mac':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', APP_DIR_NAME)

    if platform_alias == 'ios':
        return os.path.join(os.path.expanduser('~/Documents'), f'.{APP_DIR_NAME}')

    base_dir = os.environ.get('XDG_CONFIG_HOME', '').strip()
    if not base_dir:
        base_dir = os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base_dir, APP_DIR_NAME)


def load_runtime_overrides() -> dict:
    path = get_runtime_config_path()
    if not os.path.isfile(path):
        return {}

    try:
        with open(path, 'r', encoding='utf-8') as file_obj:
            data = json.load(file_obj)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    result = {}
    for key, value in data.items():
        if isinstance(key, str) and key.isupper():
            result[key] = value
    return result


def save_runtime_overrides(overrides: dict):
    if not isinstance(overrides, dict):
        raise TypeError('runtime overrides must be a dict')

    path = get_runtime_config_path()
    directory = os.path.dirname(os.path.abspath(path)) or '.'

    normalized = {}
    for key, value in overrides.items():
        if isinstance(key, str) and key.isupper():
            normalized[key] = value

    # 没有 override 时直接删除 JSON，避免以后误判为仍有本地配置。
    if not normalized:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass
        return path

    os.makedirs(directory, exist_ok=True)

    payload = {
        '_meta': {
            'warning': 'This file contains local overrides for client.config.runtime_config defaults.',
            'note': 'Only keys different from runtime_config.py defaults should be stored here.',
            'manage_with': 'set / set --reset KEY / set --reset-all',
        }
    }
    payload.update(normalized)

    fd, temp_path = tempfile.mkstemp(prefix='.rch_runtime_config_', suffix='.json.tmp', dir=directory)
    register_temp_path(temp_path)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2, sort_keys=True)
            file_obj.write('\n')
        os.replace(temp_path, path)
    except Exception:
        cleanup_temp_path(temp_path)
        raise
    finally:
        release_temp_path(temp_path)

    return path


def update_runtime_override(key: str, value):
    normalized_key = str(key or '').strip().upper()
    if not normalized_key:
        raise ValueError('runtime config key is required')
    if not normalized_key.isupper():
        raise ValueError(f'invalid runtime config key: {key}')

    overrides = load_runtime_overrides()
    overrides[normalized_key] = value
    return save_runtime_overrides(overrides)


def remove_runtime_override(key: str):
    normalized_key = str(key or '').strip().upper()
    if not normalized_key:
        raise ValueError('runtime config key is required')

    overrides = load_runtime_overrides()
    overrides.pop(normalized_key, None)
    return save_runtime_overrides(overrides)


def clear_runtime_overrides():
    return save_runtime_overrides({})