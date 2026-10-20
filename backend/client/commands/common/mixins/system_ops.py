import os
import subprocess

from client.commands.common.services.network.netstat_service import NetstatService
from client.commands.common.services.network.network_interface_service import NetworkInterfaceService
from core.utils.decorator import desc


class CommandSystemMixin:
    """
    通用系统信息/系统操作命令。
    """


    @desc('Get current user ID/name', group='system')
    def getuid(self):
        """获取当前用户名"""
        import getpass
        return 1, getpass.getuser()

    @desc('Print working directory', group='system')
    def pwd(self):
        """显示当前工作目录"""
        return 1, os.getcwd()

    @desc('Simulate keyboard input', group='system')
    def keyboard_send(self, text):
        """模拟键盘输入文字"""
        try:
            import pyautogui
            pyautogui.write(text)
            return 1, f'Typed: {text}'
        except ImportError:
            return 0, 'pyautogui not installed'

    @desc('Get current process ID', group='system')
    def getpid(self):
        """获取当前进程PID"""
        return 1, str(os.getpid())

    @desc('Show network IP addresses', group='network')
    def ip(self):
        """显示内网IP、外网IP和归属地"""
        import requests

        local_ips = []

        try:
            rows = self._get_network_interface_service().collect_ifconfig_rows()

            for row in rows:
                ip_text = str(row.get('ip') or '').strip()
                if not ip_text:
                    continue

                for ip in ip_text.split(','):
                    ip = ip.strip()
                    if ip and ip not in local_ips:
                        local_ips.append(ip)
        except Exception:
            local_ips = []

        try:
            resp = requests.get('http://ip-api.com/json/', timeout=5)
            data = resp.json()
            public_ip = data.get('query', 'Unknown')
            city = data.get('city', 'Unknown')
            region = data.get('regionName', 'Unknown')
            country = data.get('country', 'Unknown')
            isp = data.get('isp', 'Unknown')
            location = f"{city}, {region}, {country} ({isp})"
        except Exception:
            public_ip = 'Unable to determine'
            location = 'Unknown'

        local_ip_text = chr(10).join(local_ips) if local_ips else 'Unable to determine'

        result = f"Local IPs:\n  {local_ip_text}\n\nPublic IP: {public_ip}\nLocation: {location}"
        return 1, result

    @desc('List system user accounts', group='system')
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

    @desc('Check if current session is root', group='system')
    def is_root(self):
        """检查当前是否为 root 权限"""
        if os.name == 'nt':
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            return 1, f'Is admin: {is_admin}'

        is_root = os.geteuid() == 0
        return 1, f'Is root: {is_root}'

    @desc('Show system uptime', group='system')
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

    @desc('List installed third-party Python packages', group='system')
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

    def _get_network_interface_service(self):
        service = getattr(self, '_network_interface_service', None)

        if service is None:
            service = NetworkInterfaceService(self)
            self._network_interface_service = service

        return service

    def _get_netstat_service(self):
        service = getattr(self, '_netstat_service', None)

        if service is None:
            service = NetstatService(self)
            self._netstat_service = service

        return service

    @desc('Show network interfaces', group='network')
    def ifconfig(self, arg=''):
        """
        shell-like ifconfig.

        用法：
        - ifconfig
        - ifconfig json

        参数保持简单，不做端口、过滤等复杂解析。
        """
        try:
            return self._get_network_interface_service().build_ifconfig_result()
        except Exception as e:
            return 0, 'Failed to get network interfaces: {}'.format(e)

    def _acmd_netstat_common(self, args_dict, payload=None):
        """
        acmd netstat 公共实现。

        注意：
        - 不在这里加 @argument_command
        - iOS 不注册 netstat
        - mac / linux / win 平台类自己注册
        """
        return self._get_netstat_service().build_acmd_netstat_result(args_dict)