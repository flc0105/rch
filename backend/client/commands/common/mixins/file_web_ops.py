import json
import os

import requests

from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.commands.runtime.interrupts import cancel_policy
from client.runtime.filesystem.preview_image_service import PreviewImageService
from client.config import runtime_config
from core.utils.decorator import desc


class CommandFileWebMixin:
    """
    HTTP 版路径命令 mixin。

    说明：
    - 文件不再通过 socket 传输
    - client 通过 HTTP 上传到 server
    - 上传时显式上报：
      - artifact_type
      - category
      - source_type
      - source_command_id
      以便服务端正确分类并挂回 execution history
    - HTTP 传输支持两种模式：
      - legacy：保留原版 requests files=/iter_content 行为，不支持取消
      - cancelable：支持取消和实时进度
    """

    @property
    def preview_image_service(self):
        service = getattr(self, '_preview_image_service', None)
        if service is None:
            service = PreviewImageService()
            self._preview_image_service = service
        return service

    @desc('Download a file by path', group='file_path', suggest=False, output='stream')
    @cancel_policy('cooperative')
    def download_path(self, path=''):
        """
        下载单个路径到 server artifact files 区
        """
        try:
            if runtime_config.HTTP_TRANSFER_MODE == 'legacy':
                self._set_cancel_policy(
                    mode='none',
                    message='Current HTTP transfer mode is legacy; download cancellation is not supported')

            payload = self.structured_arg_codec.decode(path)
            if isinstance(payload, dict):
                transfer_id = str(payload.get('transfer_id') or '').strip()
                source_path = payload.get('path', '')
            else:
                transfer_id = ''
                source_path = path

            file_path = self.path_resolver.require_existing_file_from_arg(source_path)
            return self.http_file_transfer_service.upload_single_file_to_server_result(
                file_path,
                artifact_type='saved',
                category='downloads',
                transfer_id=transfer_id,
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except requests.Timeout:
            return 0, 'HTTP request timed out'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to download file via HTTP: {e}'

    @desc('Download multiple paths as ZIP archive', group='file_path', suggest=False, output='stream')
    @cancel_policy('cooperative')
    def download_paths(self, arg=''):
        """
        按路径列表打包上传到 server artifact files 区
        """
        try:
            payload = self.structured_arg_codec.decode(arg)
            if not isinstance(payload, dict):
                return 0, 'Invalid download payload'

            raw_paths = payload.get('paths') or []
            archive_name = (payload.get('archive_name') or '').strip()
            transfer_id = str(payload.get('transfer_id') or '').strip()

            if not isinstance(raw_paths, list) or not raw_paths:
                return 0, 'paths is required'

            resolved_paths = self.path_resolver.require_existing_paths_from_list(raw_paths)

            return self.http_file_transfer_service.upload_paths_as_zip_to_server_result(
                resolved_paths,
                archive_name=archive_name,
                artifact_type='saved',
                category='downloads',
                transfer_id=transfer_id,
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except requests.Timeout:
            return 0, 'HTTP request timed out'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to download paths via HTTP: {e}'






    @desc('Preview a file by path', group='file_path', suggest=False, output='stream')
    def preview_path(self, path=''):
        """
        拉取预览文件到 server artifact previews 区。
        如果本地配置开启 preview 图片压缩，则只在这里尝试压缩图片后上传。
        """
        prepared_file = None
        try:
            file_path = self.path_resolver.require_existing_file_from_arg(path)
            prepared_file = self.preview_image_service.prepare_upload_file(file_path)
            return self.http_file_transfer_service.upload_single_file_to_server_result(
                prepared_file.upload_path,
                artifact_type='preview',
                extra=prepared_file.extra,
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except requests.Timeout:
            return 0, 'HTTP request timed out'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to preview file via HTTP: {e}'
        finally:
            if prepared_file is not None:
                self.preview_image_service.cleanup_upload_file(prepared_file)







