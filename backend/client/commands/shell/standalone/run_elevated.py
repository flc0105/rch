"""Execute a requested command through the native authorization prompt."""
import subprocess

from client.commands.platform.utils.mac_util import escape_osascript_text
from client.commands.shell.decorators import shell_command
from core.utils.decorator import confirm


@shell_command('Run a command with elevated privileges', group='privilege', platforms=('mac', 'win'))
@confirm('This may show an operating system permission prompt and wait for authorization. Continue?',
         platform_messages={'win': 'This may show a Windows UAC permission prompt and wait for authorization. Continue?'})
def run_elevated(self, command):
    run = {'mac': _run_elevated_mac, 'win': _run_elevated_win}
    return run[self.command_platform](command)


def _run_elevated_mac(command):
    """以 root 权限执行命令 (macOS)"""
    try:
        result = subprocess.run(
            ['osascript', '-e', f'do shell script "{escape_osascript_text(command)}" with administrator privileges'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return 1, result.stdout
        return 0, result.stderr
    except Exception as e:
        return 0, f'Failed: {e}'


def _run_elevated_win(command):
    import ctypes
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            'runas',
            'cmd.exe',
            f'/c {command}',
            None,
            1,
        )
        if result > 32:
            return 1, f'Executed: {command}'
        return 0, f'Failed with code: {result}'
    except Exception as e:
        return 0, f'Failed: {e}'
