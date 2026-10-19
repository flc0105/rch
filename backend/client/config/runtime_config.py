"""
命令运行时与 HTTP 传输相关配置。

说明：
- 不改动原有 client.config.config
- 将 HTTP 传输模式、buffer 与 idle timeout 等新能力集中到这里
- HTTP_TRANSFER_MODE:
  - legacy: 保留原版 requests files=... / iter_content() 行为，不支持取消
  - cancelable: 使用可取消并支持实时进度的流式实现
- SCREEN_FRAME_STRATEGY:
  - full_jpeg: 保留原有整屏 JPEG Screen View
  - keyframe_delta: 使用 Keyframe + 自包含差分帧
- 本文件只提供默认值；运行时 set 命令写入外部 runtime_config.json 覆盖文件，不修改本源码文件
"""

from core import transfer_settings


# ------------------ command runtime ------------------ #
# 通用命令兜底超时：只在命令没有更具体的 fallback timeout 时生效。
# 不覆盖 shell / stream / HTTP 等命令自己的专用 timeout。
COMMAND_DEFAULT_TIMEOUT = None
COMMAND_DEFAULT_SHELL_TIMEOUT = 30
COMMAND_DEFAULT_STREAM_TIMEOUT = 300

# ------------------ http transfer strategy ------------------ #
# HTTP_TRANSFER_MODE = 'cancelable'
HTTP_TRANSFER_MODE = 'legacy'

# ------------------ http file transfer ------------------ #
# 所有 HTTP 文件传输统一使用同一个 buffer。
HTTP_TRANSFER_BUFFER_SIZE = transfer_settings.DEFAULT_HTTP_TRANSFER_BUFFER_SIZE

# 不限制文件传输总时长；仅在启用后，对单次网络 I/O 长时间无推进进行停止。
# 默认 6 小时，适合超大文件/弱网环境，仍可在 Configuration 中调整或关闭。
HTTP_TRANSFER_IDLE_TIMEOUT_ENABLED = True
HTTP_TRANSFER_IDLE_TIMEOUT_SECONDS = 6 * 60 * 60

# ------------------ preview image compression ------------------ #
# 只影响 preview_path 的 web 预览上传，不影响 download_path / 平台命令 / script 上传。
PREVIEW_IMAGE_COMPRESS_ENABLED = False
PREVIEW_IMAGE_COMPRESS_QUALITY = 75

# PYTHON_EXECUTION_MODE = 'subprocess_pipe'
PYTHON_EXECUTION_MODE = 'inproc'

# ------------------ screen view strategy ------------------ #
# SCREEN_FRAME_STRATEGY = 'keyframe_delta'
SCREEN_FRAME_STRATEGY = 'full_jpeg'


RECONNECT_INTERVAL_SECONDS = 5
REMOTE_HTTP_WATCHDOG_ENABLED = False
REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS = 15
LOCAL_WATCHDOG_ENABLED = False
LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS = 5
LOCAL_WATCHDOG_TIMEOUT_SECONDS = 15

# Independent process-death recovery; unrelated to the local heartbeat watchdog.
PROCESS_WATCHDOG_ENABLED = False


# runtime_config 暴露元信息。
# expose=True 的配置会出现在普通 set 输出和 set 自动补全中，也允许通过 set KEY value 修改。
# expose=False 的配置保留在本文件和 set --all 输出中，但默认不允许直接 set 修改。
# 如果以后希望隐藏项也允许修改，把 RuntimeConfigService.is_supported_key() 改为调用 is_known_config_key() 即可。
_RUNTIME_CONFIG_DEPRECATED_KEYS = {
    'HTTP_UPLOAD_TIMEOUT',
    'HTTP_DOWNLOAD_CONNECT_TIMEOUT',
    'HTTP_DOWNLOAD_READ_TIMEOUT',
}


_RUNTIME_CONFIG_META = {
    'COMMAND_DEFAULT_TIMEOUT': {
        'group': 'command',
        'expose': False,
        'desc': 'Default command context timeout.',
    },
    'COMMAND_DEFAULT_SHELL_TIMEOUT': {
        'group': 'command',
        'expose': True,
        'desc': 'Default timeout for shell command execution.',
    },
    'COMMAND_DEFAULT_STREAM_TIMEOUT': {
        'group': 'command',
        'expose': True,
        'desc': 'Default timeout for stream command execution.',
    },
    'HTTP_TRANSFER_MODE': {
        'group': 'transfer',
        'expose': True,
        'desc': 'HTTP transfer implementation mode: legacy or cancelable.',
        'choices': ['legacy', 'cancelable'],
    },
    'HTTP_TRANSFER_BUFFER_SIZE': {
        'group': 'transfer',
        'expose': True,
        'desc': 'Shared HTTP file transfer buffer size in bytes.',
        'min': transfer_settings.MIN_HTTP_TRANSFER_BUFFER_SIZE,
        'max': transfer_settings.MAX_HTTP_TRANSFER_BUFFER_SIZE,
        'step': transfer_settings.MIN_HTTP_TRANSFER_BUFFER_SIZE,
    },
    'HTTP_TRANSFER_IDLE_TIMEOUT_ENABLED': {
        'group': 'transfer',
        'expose': True,
        'desc': 'Stop an HTTP file transfer when network I/O makes no progress for the configured idle timeout.',
    },
    'HTTP_TRANSFER_IDLE_TIMEOUT_SECONDS': {
        'group': 'transfer',
        'expose': True,
        'desc': 'Maximum seconds without HTTP file transfer I/O progress. Default: 21600 seconds (6 hours).',
        'min': 1,
        'max': 604800,
        'step': 60,
    },
    'PREVIEW_IMAGE_COMPRESS_ENABLED': {
        'group': 'preview',
        'expose': True,
        'desc': 'Enable image compression before preview upload.',
    },
    'PREVIEW_IMAGE_COMPRESS_QUALITY': {
        'group': 'preview',
        'expose': True,
        'desc': 'JPEG quality used for compressed preview images.',
    },
    'PYTHON_EXECUTION_MODE': {
        'group': 'strategy',
        'expose': True,
        'desc': 'Python script execution mode: inproc or subprocess_pipe.',
        'choices': ['inproc', 'subprocess_pipe'],
    },
    'SCREEN_FRAME_STRATEGY': {
        'group': 'strategy',
        'expose': True,
        'desc': 'Screen View frame strategy: full_jpeg or keyframe_delta. Applies to new screen sessions.',
        'choices': ['full_jpeg', 'keyframe_delta'],
    },
    'RECONNECT_INTERVAL_SECONDS': {
        'group': 'connection',
        'expose': True,
        'desc': 'Reconnect interval after client connection loss.',
    },
    'REMOTE_HTTP_WATCHDOG_ENABLED': {
        'group': 'watchdog',
        'expose': True,
        'desc': 'Enable remote HTTP watchdog.',
    },
    'REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS': {
        'group': 'watchdog',
        'expose': False,
        'desc': 'Remote HTTP watchdog check interval in seconds.',
    },
    'LOCAL_WATCHDOG_ENABLED': {
        'group': 'watchdog',
        'expose': True,
        'desc': 'Enable local watchdog heartbeat.',
    },
    'LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS': {
        'group': 'watchdog',
        'expose': False,
        'desc': 'Local watchdog heartbeat interval in seconds.',
    },
    'LOCAL_WATCHDOG_TIMEOUT_SECONDS': {
        'group': 'watchdog',
        'expose': False,
        'desc': 'Local watchdog timeout in seconds.',
    },
    'PROCESS_WATCHDOG_ENABLED': {
        'group': 'watchdog',
        'expose': True,
        'desc': 'Restart the Client if its operating-system process unexpectedly exits.',
    },
}


# 记录源码默认值。set 命令会用它判断 override 是否冗余。
_RUNTIME_CONFIG_DEFAULTS = {
    _key: _value
    for _key, _value in list(globals().items())
    if _key.isupper() and isinstance(_value, (str, int, float, bool, type(None)))
}


# 外部 runtime_config.json 覆盖默认值。这里不写源码文件，兼容打包场景。
try:
    from client.config.runtime_config_store import load_runtime_overrides, get_runtime_config_path

    _RUNTIME_CONFIG_OVERRIDE_PATH = get_runtime_config_path()
    _RUNTIME_CONFIG_OVERRIDE_KEYS = []

    for _key, _value in load_runtime_overrides().items():
        if _key in globals() and _key.isupper():
            globals()[_key] = _value
            _RUNTIME_CONFIG_OVERRIDE_KEYS.append(_key)
except Exception:
    _RUNTIME_CONFIG_OVERRIDE_PATH = ''
    _RUNTIME_CONFIG_OVERRIDE_KEYS = []
finally:
    try:
        del load_runtime_overrides
    except Exception:
        pass
    try:
        del get_runtime_config_path
    except Exception:
        pass
    try:
        del _key
    except Exception:
        pass
    try:
        del _value
    except Exception:
        pass