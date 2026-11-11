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

            self.owner._send_interim_result(1, 'Capturing screenshot...', 0)

            # 创建临时文件
            temp_fd, temp_path = make_client_temp_file(
                'media_temp',
                prefix='screenshot_',
                suffix='.png',
            )
            os.close(temp_fd)
            temp_file = temp_path
            self.owner._send_interim_result(1, f'Client Temp Path: {temp_file}', 0)

            # 截图
            screenshot = pyautogui.screenshot()
            screenshot.save(temp_file)

            file_size = os.path.getsize(temp_file)
            self.owner._send_interim_result(1, f'Screenshot captured ({file_size} bytes)', 0)

            # 上传文件
            filename = build_artifact_filename('screenshot', 'png')
            self.owner.http_file_transfer_service.upload_single_file_to_server_result(
                temp_file,
                category='screenshots',
                upload_name=filename,
                extra={'saved_from': 'client_command', 'source_command': 'screenshot'},
            )

            self.owner._send_final_result(1, f'Screenshot uploaded: {filename}')

        except Exception as e:
            self.owner._send_final_result(0, f'Screenshot failed: {e}')
        finally:
            if temp_file:
                cleanup_temp_path(temp_file)