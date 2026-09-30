import platform

from .macos import MacOSNotificationBackend
from .windows import WindowsNotificationBackend


def create_notification_backend(name: str = 'auto', *, sound: bool = True):
    normalized = str(name or 'auto').strip().lower()
    system = platform.system().lower()

    if normalized in {'usernotifications', 'osascript'}:
        return MacOSNotificationBackend(mode=normalized, sound=sound)
    if normalized == 'windows':
        return WindowsNotificationBackend(sound=sound)

    if system == 'darwin':
        return MacOSNotificationBackend(mode='auto', sound=sound)
    if system == 'windows':
        return WindowsNotificationBackend(sound=sound)
    raise RuntimeError(f'Unsupported desktop notification platform: {platform.system()}')
