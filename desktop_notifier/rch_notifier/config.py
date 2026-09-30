import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NotifierConfig:
    server_url: str
    token: str
    sound: bool = True
    backend: str = 'auto'
    reconnect_initial_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0

    @property
    def stream_url(self) -> str:
        return self.server_url.rstrip('/') + '/api/notifications/stream'


def default_config_path() -> Path:
    system = platform.system().lower()
    if system == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'RCH Notifier' / 'config.json'
    if system == 'windows':
        base = Path(os.environ.get('APPDATA') or (Path.home() / 'AppData' / 'Roaming'))
        return base / 'RCH Notifier' / 'config.json'
    return Path(os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config')) / 'rch-notifier' / 'config.json'


def default_state_path(config_path: Path) -> Path:
    return config_path.with_name('state.json')


def load_config(path: Path) -> NotifierConfig:
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ValueError('Notifier config must be a JSON object')

    server_url = str(os.getenv('RCH_NOTIFIER_SERVER_URL') or raw.get('server_url') or '').strip().rstrip('/')
    token = str(os.getenv('RCH_NOTIFIER_TOKEN') or raw.get('token') or '').strip()
    backend = str(os.getenv('RCH_NOTIFIER_BACKEND') or raw.get('backend') or 'auto').strip().lower()
    if not server_url:
        raise ValueError('server_url is required')
    if not token:
        raise ValueError('token is required; use the RCH API token for this first version')
    if backend not in {'auto', 'usernotifications', 'osascript', 'windows'}:
        raise ValueError(f'Unsupported notification backend: {backend}')

    initial = float(raw.get('reconnect_initial_seconds', 1) or 1)
    maximum = float(raw.get('reconnect_max_seconds', 30) or 30)
    if initial <= 0 or maximum <= 0 or initial > maximum:
        raise ValueError('Reconnect delays must be positive and initial <= max')

    return NotifierConfig(
        server_url=server_url,
        token=token,
        sound=bool(raw.get('sound', True)),
        backend=backend,
        reconnect_initial_seconds=initial,
        reconnect_max_seconds=maximum,
    )


def write_example_config(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f'Config already exists: {path}')
    payload = {
        'server_url': 'http://127.0.0.1:8085',
        'token': 'REPLACE_WITH_RCH_ADMIN_API_TOKEN',
        'sound': True,
        'backend': 'auto',
        'reconnect_initial_seconds': 1,
        'reconnect_max_seconds': 30,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path
