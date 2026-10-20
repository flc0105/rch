from client.commands.runtime.interrupts import cancel_policy
import os

from client.config.runtime_config import HTTP_TRANSFER_MODE
from core.utils.decorator import desc
from core.utils.output_marker import error, success, info


class CommandFileCliMixin:
    @desc('Download a file from the client', group='transfer')
    def download(self, filename=''):
        """
        旧版为 socket 发送文件。
        现改为 client 直接通过 HTTP 上传到 server artifact 区。
        """
        try:
            if not str(filename or '').strip():
                return 0, 'Usage: download <file>'
            if HTTP_TRANSFER_MODE == 'legacy':
                self._set_cancel_policy(
                    mode='none',
                    message='Current HTTP transfer mode is legacy; download cancellation is not supported')

            file_path = self.path_resolver.require_existing_file_from_arg(filename)
            return self.http_file_transfer_service.upload_single_file_to_server_result(
                file_path,
                category='download'
            )
        except Exception as e:
            return 0, f'Failed to download file: {e}'


    @desc('Receive a file from server via HTTP', group='file', suggest=False)
    def receive_file(self, arg=''):
        """
        通过普通命令下发 HTTP 拉取任务，由 client 自己去 server 拉文件并保存到本地。

        结构化参数：
        - relative_url: server 提供的临时下载相对地址
        - url: 兼容旧字段，完整下载地址
        - filename: 保存时使用的文件名
        - save_dir: 目标目录（可空，空则当前工作目录）
        """
        try:

            # 如果传输模式为legacy在正式上传之前设置不可取消
            if HTTP_TRANSFER_MODE == 'legacy':
                self._set_cancel_policy(
                    mode='none',
                    message='Current HTTP transfer mode is legacy; upload cancellation is not supported')

            payload = self.structured_arg_codec.decode(arg)
            if not isinstance(payload, dict):
                return 0, error('Invalid HTTP upload payload')

            relative_url = str(payload.get('relative_url') or '').strip()
            url = str(payload.get('url') or '').strip()
            filename = str(payload.get('filename') or '').strip()
            save_dir = str(payload.get('save_dir') or '').strip()
            transfer_id = str(payload.get('transfer_id') or '').strip()

            if not url:
                if not relative_url:
                    return 0, error('url or relative_url is required')
                url = self.client_api.normalize_file_transfer_url(relative_url)
            else:
                url = self.client_api.normalize_file_transfer_url(url)

            if not filename:
                return 0, error('filename is required')

            target_dir = self.path_resolver.resolve_target_path(save_dir or '.')
            if os.path.exists(target_dir) and not os.path.isdir(target_dir):
                return 0, error(f'Target path is not a directory: {target_dir}')

            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, os.path.basename(filename))

            self._send_info(f'Preparing HTTP download: {url}', 0)
            self.http_file_transfer_service.download_file_from_http(
                url,
                target_path,
                transfer_id=transfer_id,
            )
            file_size = os.path.getsize(target_path)

            lines = [
                success('File saved successfully via HTTP\n'),
                info(f'Path: {target_path}\n'),
                info(f'Size: {file_size} bytes'),
            ]
            return 1, ''.join(lines)

        except Exception as e:
            return 0, error(f'Failed to receive file via HTTP: {e}')

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