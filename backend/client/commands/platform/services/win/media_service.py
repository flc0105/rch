import os

from core.utils.artifact_naming import build_artifact_filename
from client.runtime.temp_workspace import make_client_temp_file, cleanup_temp_path


class WinMediaService:
    """
    Windows 截图/媒体能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def capture_screenshot(self):
        temp_file = None
        try:
            import pyautogui

            self.owner.emit_progress('Capturing screenshot...', level='info')

            # 创建临时文件
            temp_fd, temp_path = make_client_temp_file(
                'media_temp',
                prefix='screenshot_',
                suffix='.png',
            )
            os.close(temp_fd)
            temp_file = temp_path
            self.owner.emit_progress(f'Client Temp Path: {temp_file}', level='info')

            # 截图
            screenshot = pyautogui.screenshot()
            screenshot.save(temp_file)

            file_size = os.path.getsize(temp_file)
            self.owner.emit_progress(f'Screenshot captured ({file_size} bytes)', level='success')

            # 上传文件
            filename = build_artifact_filename('screenshot', 'png')
            upload_status, upload_message = self.owner.http_file_transfer_service.upload_single_file_to_server_result(
                temp_file,
                category='screenshots',
                upload_name=filename,
                extra={'saved_from': 'client_command', 'source_command': 'screenshot'},
            )

            if not upload_status:
                self.owner.emit_completed(status='error', message=str(upload_message))
                return
            self.owner.emit_completed(status='success', message=f'Screenshot uploaded: {filename}')

        except Exception as e:
            self.owner.emit_completed(status='error', message=f'Screenshot failed: {e}')
        finally:
            if temp_file:
                cleanup_temp_path(temp_file)