"""Effective Server Web endpoint for Client API requests.

Reverse uses the configured endpoint. Bind receives a per-session endpoint after
registration. A small atomic snapshot lets separately spawned Script/Job workers
resolve the same endpoint without copying it into the bundled agent profile.
"""
import json
import os
import tempfile
from urllib.parse import urlsplit

from client.config.config import RUNTIME_CONFIG

_STATE_FILE_ENV = 'RCH_SERVER_WEB_ENDPOINT_STATE'
_state_path = ''


def validate_base_url(value: str) -> str:
    url = str(value or '').strip().rstrip('/')
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.path
            or parsed.query or parsed.fragment or any(char.isspace() for char in url)):
        raise ValueError('Server Web URL must be an http(s) origin')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Invalid Server Web URL port') from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('Invalid Server Web URL port')
    return url


def _configured_base_url() -> str:
    config = RUNTIME_CONFIG
    return f"{config['server_web_scheme']}://{config['server_web_host']}:{config['server_web_port']}"


def is_bind_endpoint_mode() -> bool:
    # Child Python processes inherit the session snapshot path even when their
    # own argv does not include the main Client's --profile setting.
    return (str(RUNTIME_CONFIG.get('connection_mode') or 'reverse') == 'bind'
            or bool(os.environ.get(_STATE_FILE_ENV)))


def get_server_base_url() -> str:
    """Resolve on every request, including in spawned Script/Job/Watchdog workers."""
    path = os.environ.get(_STATE_FILE_ENV, '')
    if path:
        try:
            with open(path, 'r', encoding='utf-8') as file_obj:
                return validate_base_url(json.load(file_obj).get('base_url'))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    if is_bind_endpoint_mode():
        raise RuntimeError('Server Web URL is unavailable until the Bind session is registered')
    return _configured_base_url()


def prepare_session_endpoint() -> None:
    """Create one stable IPC snapshot path before Script/Job/Watchdog start."""
    global _state_path
    if str(RUNTIME_CONFIG.get('connection_mode') or 'reverse') != 'bind':
        # An independently restarted Reverse main process does not inherit a
        # former Bind session endpoint.
        os.environ.pop(_STATE_FILE_ENV, None)
        return
    if _state_path:
        return
    fd, _state_path = tempfile.mkstemp(prefix='rch-client-web-', suffix='.json')
    os.close(fd)
    os.environ[_STATE_FILE_ENV] = _state_path


def set_session_base_url(value: str) -> None:
    """Publish the advertised URL for this connection and its child processes."""
    global _state_path
    if str(RUNTIME_CONFIG.get('connection_mode') or 'reverse') != 'bind':
        return
    base_url = validate_base_url(value)
    prepare_session_endpoint()
    path = _state_path
    fd, temporary = tempfile.mkstemp(prefix='.rch-web-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file_obj:
            json.dump({'base_url': base_url}, file_obj)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    os.environ[_STATE_FILE_ENV] = path


def clear_session_base_url() -> None:
    """Revoke only this process's session snapshot; children fail closed on disconnect."""
    # Keep the path stable for watchdog/Job processes already holding it.
    # Reconnection atomically publishes a new value to this same location.
    if _state_path:
        try:
            os.unlink(_state_path)
        except FileNotFoundError:
            pass
