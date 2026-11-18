import os
import subprocess

from client.commands.shell.decorators import shell_command


class ShellSystemCommands:
    """
    通用系统信息/系统操作命令。
    """


    @shell_command('Get current user ID/name', group='system')
    def getuid(self):
        """获取当前用户名"""
        import getpass
        return 1, getpass.getuser()

    @shell_command('Print working directory', group='shell')
    def pwd(self):
        """显示当前工作目录"""
        return 1, os.getcwd()

    @shell_command('Simulate keyboard input', group='automation')
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

    @shell_command('List system user accounts', group='system')
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

    @shell_command('Check whether the current process has elevated privileges', group='privilege')
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
        """显示系统运行时间"""
        import psutil
        from datetime import datetime

        boot_time = psutil.boot_time()
        boot_dt = datetime.fromtimestamp(boot_time)
        now = datetime.now()
        uptime_seconds = (now - boot_dt).total_seconds()

        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        return 1, f"Boot time: {boot_dt.strftime('%Y-%m-%d %H:%M:%S')}\nUptime: {days}d {hours}h {minutes}m"

    @shell_command('List installed third-party Python packages', group='python')
    def piplist(self, arg=''):
        """列出当前 Python 环境已安装的第三方包和版本"""
        try:
            from importlib import metadata
            from core.utils.command_output import StructuredCommandResult

            packages = {}

            for distribution in metadata.distributions():
                name = str(distribution.metadata.get('Name') or '').strip()
                if not name:
                    continue

                packages[name.casefold()] = {
                    'Package': name,
                    'Version': str(distribution.version or 'unknown'),
                }

            rows = sorted(
                packages.values(),
                key=lambda item: item['Package'].casefold(),
            )

            return StructuredCommandResult(
                status=1,
                data=rows,
                shape='table',
            )

        except Exception as e:
            return 0, f'Failed to list Python packages: {e}'
