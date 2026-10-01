from client.config.runtime_config_utils import format_runtime_config_value
from client.config import runtime_config
from client.config.runtime_config_store import get_runtime_config_path
from core.utils.logger import logger



def log_runtime_config_overrides_if_any():
    """
    client 启动时输出当前生效的 runtime_config override。

    只输出真正加载进 runtime_config 的 override。
    不修改 runtime_config.py。
    不修改 runtime_config.json。
    """
    override_keys = getattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_KEYS', []) or []
    if not override_keys:
        return

    override_path = (
        getattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_PATH', '') or
        get_runtime_config_path()
    )
    defaults = getattr(runtime_config, '_RUNTIME_CONFIG_DEFAULTS', {}) or {}

    lines = [
        'Runtime config overrides are active.',
        f'Runtime config store: {override_path}',
    ]

    for key in sorted(override_keys):
        current_value = getattr(runtime_config, key, None)
        default_value = defaults.get(key, '<unknown>')
        lines.append(
            f'  {key} = {format_runtime_config_value(current_value)} '
            f'(default={format_runtime_config_value(default_value)})'
        )

    logger.warning('\n'.join(lines))