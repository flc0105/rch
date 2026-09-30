import logging
import os
import subprocess


logger = logging.getLogger(__name__)


class WindowsNotificationBackend:
    """Minimal Windows toast backend.

    This path is intentionally small because the current development environment
    has no Windows host. It uses the built-in Windows Runtime from PowerShell and
    should be treated as first-pass support until tested on a real Windows client.
    """

    def __init__(self, *, sound: bool = True):
        self.sound = bool(sound)
        self.active_mode = 'powershell'

    def start(self):
        return None

    def notify(self, notification: dict) -> bool:
        title = str((notification or {}).get('title') or 'RCH').strip() or 'RCH'
        message = str((notification or {}).get('message') or '').strip()
        env = dict(os.environ)
        env['RCH_NOTIFY_TITLE'] = title
        env['RCH_NOTIFY_BODY'] = message
        env['RCH_NOTIFY_SOUND'] = '1' if self.sound else '0'

        script = r'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$title = $env:RCH_NOTIFY_TITLE
$body = $env:RCH_NOTIFY_BODY
$sound = $env:RCH_NOTIFY_SOUND
$audio = if ($sound -eq '1') { '<audio src="ms-winsoundevent:Notification.Default" />' } else { '<audio silent="true" />' }
$escape = { param($s) [System.Security.SecurityElement]::Escape([string]$s) }
$xmlText = '<toast><visual><binding template="ToastGeneric"><text>' + (&$escape $title) + '</text><text>' + (&$escape $body) + '</text></binding></visual>' + $audio + '</toast>'
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($xmlText)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('RCH Notifier').Show($toast)
'''
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or 'Windows toast failed').strip())
        return True
