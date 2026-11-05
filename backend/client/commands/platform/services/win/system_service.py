import os
import platform
import sys

from client.config import runtime_config
from client.runtime.client_util import get_executable_path
from core.utils.command_output import StructuredCommandResult
from core.utils.logger import logger


class WinSystemService:
    """
    Windows 系统信息与用户状态能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def _load_win_util(self):
        if os.name != 'nt':
            return None
        try:
            from client.commands.platform.utils import win_util
            return win_util
        except Exception:
            return None

    def collect_system_info(self):
        try:
            import psutil

            win_util = self._load_win_util()

            info = {}
            info['pid'] = os.getpid()
            info['hostname'] = platform.node()
            info['os'] = platform.platform()
            info['os_version'] = platform.version()
            info['architecture'] = platform.machine()
            info['processor'] = platform.processor()
            info['cpu_count'] = os.cpu_count()

            # 内存信息
            mem = psutil.virtual_memory()
            info['mem_total'] = f'{mem.total / (1024 ** 3):.2f} GB'
            info['mem_avail'] = f'{mem.available / (1024 ** 3):.2f} GB'

            # 进程信息
            proc = psutil.Process()

            info['username'] = proc.username()
            # info['username_sam'] = get_sam_compatible_name()

            if win_util is not None:
                info['locale'] = win_util.get_locale_tag()
                sid_info = win_util.get_windows_uid_gid_sid()
                info['uid'] = sid_info.get('uid', '')
                info['gid'] = sid_info.get('gid', '')

                try:
                    info['integrity'] = win_util.get_integrity_level()
                except Exception:
                    info['integrity'] = ''
            else:
                info['locale'] = ''
                info['uid'] = ''
                info['gid'] = ''
                info['integrity'] = ''

            info['exec_path'] = get_executable_path()
            info['reconnect_interval'] = runtime_config.RECONNECT_INTERVAL_SECONDS
            info['cwd'] = os.getcwd()

            # Python 信息
            info['python_version'] = sys.version

            return StructuredCommandResult(
                status=1,
                data=info,
                shape='dict',
                width=20,
            )

        except Exception as e:
            logger.error(e, exc_info=True)
            return 0, f'Failed to get system info: {e}'

    def get_user_idletime(self):
        try:
            import win32api

            idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
            idle_seconds = idle_ms / 1000.0

            return 1, f'User idle time: {idle_seconds:.2f} seconds'

        except Exception as e:
            return 0, f'Failed to get idle time: {e}'