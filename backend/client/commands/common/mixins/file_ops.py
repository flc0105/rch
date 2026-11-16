from client.commands.runtime.interrupts import cancel_policy

from client.config import runtime_config
from core.utils.decorator import desc
from core.command_completion.models import CompletionSpec


class CommandFileMixin:
    @desc('Download a file from the client', group='transfer', output='stream', completion=CompletionSpec('filesystem', ('file', 'directory')))
    @cancel_policy('cooperative')
    def download(self, filename=''):
        """
        旧版为 socket 发送文件。
        现改为 client 直接通过 HTTP 上传到 server artifact 区。
        """
        try:
            if not str(filename or '').strip():
                return 0, 'Usage: download <file>'
            if runtime_config.HTTP_TRANSFER_MODE == 'legacy':
                self._set_cancel_policy(
                    mode='none',
                    message='Current HTTP transfer mode is legacy; download cancellation is not supported')

            file_path = self.path_resolver.require_existing_file_from_arg(filename)
            return self.http_file_transfer_service.upload_single_file_to_server_result(
                file_path,
                category='downloads',
                extra={'saved_from': 'client_command', 'source_command': f'download {filename}'},
            )
        except Exception as e:
            return 0, f'Failed to download file: {e}'


    @desc('Create a ZIP archive', group='file')
    @cancel_policy('cooperative')
    def zip_dir(self, dir_name):
        """
        按命令行参数压缩目录。
        """
        try:
            archive_path = self.archive_service.create_zip_archive(dir_name)
            return 1, f'Archive created successfully: {archive_path}'
        except Exception as e:
            return 0, f'Failed to create archive: {e}'

    @desc('Extract a ZIP archive', group='file')
    @cancel_policy('cooperative')
    def unzip(self, zip_name):
        """
        按命令行参数解压压缩包到当前工作目录。
        """
        try:
            archive_path = self.path_resolver.validate_file_exists(zip_name)
            self.archive_service.extract_archive_to_cwd(archive_path)
            return 1, f'Archive extracted to: {self.path_resolver.get_current_directory()}'
        except Exception as e:
            return 0, f'Failed to extract archive: {e}'