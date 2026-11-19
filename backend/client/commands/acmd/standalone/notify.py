"""Send a native local notification on the target Client."""
import os
import subprocess

from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec


NOTIFY_SPEC = ArgumentCommandSpec(
    name='notify',
    description='Show a native notification on the Client',
    options=[
        ArgumentOptionSpec('title', 'str', default='', help_text='Notification title'),
        ArgumentOptionSpec('message', 'str', required=True, allow_empty=False, help_text='Notification message'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)


@argument_command('notify', spec=NOTIFY_SPEC, platforms=('mac', 'win', 'ios'))
def notify(self, args_dict):
    title = args_dict['title'].strip() or 'RCH'
    try:
        show = {'mac': _notify_mac, 'win': _notify_windows, 'ios': _notify_ios}
        show[self.command_platform](self, title, args_dict['message'])
        return 1, 'Notification requested.'
    except (OSError, RuntimeError, ImportError, ValueError, subprocess.SubprocessError) as exc:
        return 0, f'Could not send the notification: {exc}'


def _notify_mac(owner, title, message):
    automation = owner.mac_automation
    title = automation.escape_osascript_text(title)
    message = automation.escape_osascript_text(message)
    result = subprocess.run(
        ['osascript', '-e', f'display notification "{message}" with title "{title}"'],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'macOS rejected the notification')


def _notify_windows(owner, title, message):
    # A tray balloon avoids requiring a separately registered toast app identity.
    script = """$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
try {
    $icon.Icon = [System.Drawing.SystemIcons]::Information
    $icon.Visible = $true
    $icon.ShowBalloonTip(5000, $env:RCH_NOTIFY_TITLE, $env:RCH_NOTIFY_MESSAGE,
                         [System.Windows.Forms.ToolTipIcon]::Info)
    $until = [DateTime]::UtcNow.AddSeconds(6)
    while ([DateTime]::UtcNow -lt $until) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 100
    }
} finally {
    $icon.Dispose()
}
"""
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-Command', script],
        env={**os.environ, 'RCH_NOTIFY_TITLE': title, 'RCH_NOTIFY_MESSAGE': message},
        capture_output=True, text=True, errors='replace', timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Windows rejected the notification')


def _notify_ios(owner, title, message):
    import notification

    notification.schedule(message, delay=0, title=title)
