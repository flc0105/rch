"""Show a local, native message box on a Client with a desktop or Pythonista UI."""
import os
import subprocess

from client.commands.acmd.decorators import argument_command
from client.runtime.ios_util import show_ios_alert
from client.runtime.mac_util import escape_osascript_text
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec


MSGBOX_SPEC = ArgumentCommandSpec(
    name='msgbox',
    description='Show a native message box on the Client',
    options=[
        ArgumentOptionSpec('title', 'str', default='', help_text='Dialog title'),
        ArgumentOptionSpec('message', 'str', required=True, allow_empty=False, help_text='Dialog message'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)


@argument_command('msgbox', spec=MSGBOX_SPEC, platforms=('mac', 'win', 'ios'))
def msgbox(self, args_dict):
    title = args_dict['title'].strip() or 'RCH'
    try:
        show = {'mac': _show_mac_message_box, 'win': _show_windows_message_box, 'ios': _show_ios_message_box}
        show[self.command_platform](self, title, args_dict['message'])
        return 1, 'Message box requested.'
    except (OSError, RuntimeError, ImportError, ValueError) as exc:
        return 0, f'Could not show the message box: {exc}'


def _show_mac_message_box(owner, title, message):
    title = escape_osascript_text(title)
    message = escape_osascript_text(message)
    process = subprocess.Popen(
        ['osascript', '-e', f'display dialog "{message}" with title "{title}" buttons {{"OK"}}'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    owner._register_cancel_handler(lambda: owner.process_execution_service.terminate_process(process))


def _show_windows_message_box(owner, title, message):
    # Pass user text as data to a fixed script, including quotes and line breaks.
    script = """$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[void][System.Windows.Forms.MessageBox]::Show($env:RCH_DIALOG_MESSAGE, $env:RCH_DIALOG_TITLE)
"""
    process = subprocess.Popen(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-Command', script],
        env={**os.environ, 'RCH_DIALOG_TITLE': title, 'RCH_DIALOG_MESSAGE': message},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    owner._register_cancel_handler(lambda: owner.process_execution_service.terminate_process(process))


def _show_ios_message_box(owner, title, message):
    show_ios_alert(title, message)
