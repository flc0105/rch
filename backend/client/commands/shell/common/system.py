import os
import subprocess
import time
from datetime import datetime

from client.commands.shell.decorators import shell_command
from client.commands.shell.standalone.getinfo import getinfo
from client.commands.shell.standalone.idletime import idletime
from client.commands.shell.standalone.run_elevated import run_elevated
from client.commands.shell.standalone.spawn_elevated_instance import spawn_elevated_instance


def _desktop_boot_time():
    import psutil

    return psutil.boot_time()


def _ios_boot_time():
    from objc_util import ObjCClass

    seconds = max(0, float(ObjCClass('NSProcessInfo').processInfo().systemUptime()))
    return time.time() - seconds


@shell_command('Get current user ID/name', group='system')
def getuid(self):
    """获取当前用户名"""
    import getpass
    return 1, getpass.getuser()
@shell_command('Print working directory', group='shell')
def pwd(self):
    """显示当前工作目录"""
    return 1, os.getcwd()
@shell_command('Simulate keyboard input', group='automation', platforms=('mac', 'win', 'linux'))
def keyboard_send(self, text):
    """模拟键盘输入文字"""
    try:
        import pyautogui
        pyautogui.write(text)
        return 1, f'Typed: {text}'
    except ImportError:
        return 0, 'pyautogui not installed'
@shell_command('Get current process ID', group='system')
def getpid(self):
    """获取当前进程PID"""
    return 1, str(os.getpid())
@shell_command('List system user accounts', group='system', platforms=('mac', 'win', 'linux'))
def userenum(self):
    """列出系统用户账户"""
    try:
        import pwd

        current_user = os.getlogin()
        users = []

        for user in pwd.getpwall():
            # macOS: 普通用户 UID 通常是 501 开始
            # 包含当前用户和所有 UID >= 500 的用户
            if user.pw_uid >= 500 or user.pw_name in ['root', 'admin', '_mbsetupuser']:
                marker = ' [current]' if user.pw_name == current_user else ''
                users.append(f"{user.pw_name} (UID: {user.pw_uid}){marker}")

        return 1, '\n'.join(sorted(users, key=lambda x: x.split('UID:')[1].split(')')[0]))
    except Exception:
        result = subprocess.run('net user', shell=True, capture_output=True, text=True)
        return 1, result.stdout
@shell_command('Check whether the current process has elevated privileges', group='privilege', platforms=('mac', 'win', 'linux'))
def is_elevated(self):
    """检查当前是否为 root 权限"""
    if os.name == 'nt':
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        return 1, f'Is admin: {is_admin}'

    is_root = os.geteuid() == 0
    return 1, f'Is root: {is_root}'
@shell_command('Show system uptime', group='system')
def uptime(self):
    boot_time_for = {
        'mac': _desktop_boot_time, 'win': _desktop_boot_time,
        'linux': _desktop_boot_time, 'ios': _ios_boot_time,
    }
    try:
        started = boot_time_for[self.command_platform]()
        boot_time = datetime.fromtimestamp(started)
        minutes = int(max(0, time.time() - started)) // 60
        days, minutes = divmod(minutes, 24 * 60)
        hours, minutes = divmod(minutes, 60)
        return 1, f"Boot time: {boot_time:%Y-%m-%d %H:%M:%S}\nUptime: {days}d {hours}h {minutes}m"
    except Exception as exc:
        return 0, f'Failed to get system uptime: {exc}'
