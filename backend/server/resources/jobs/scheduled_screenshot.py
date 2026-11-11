JOB_METADATA = {
    "name": "scheduled_screenshot",
    "display_name": "Scheduled Screenshot",
    "description": "Capture screenshots periodically and upload them",
    "platforms": ["darwin", "windows"],
    "params": [
        {
            "name": "interval_seconds",
            "type": "integer",
            "required": False,
            "default": 30,
            "min": 1,
            "description": "Capture interval in seconds"
        }
    ]
}

import os
import threading
import time

import schedule

from client.jobs.core.job import Job
from core.utils.artifact_naming import build_artifact_filename
from core.utils.logger import logger


class ScheduledScreenshot(Job):
    def __init__(self):
        super().__init__()
        self.interval_seconds = 30  # 30秒一次

    def on_context_bound(self):
        self.interval_seconds = int(self.get_job_param('interval_seconds', 30) or 30)

    def _capture_screenshot(self, filename: str):
        if os.name == 'nt':
            import pyautogui
            pyautogui.screenshot(filename)
            return

        if os.name == 'posix':
            os.system(f'screencapture -x {filename}')
            return

        raise RuntimeError('Unsupported operating system')

    def _run_capture_task(self):
        screenshot_name = build_artifact_filename('screenshot', 'png')
        self._capture_screenshot(screenshot_name)

        screenshot_path = os.path.abspath(screenshot_name)
        if not os.path.isfile(screenshot_path):
            self.send_to_server(0, f'Screenshot file not found: {screenshot_path}', 0)
            return

        try:
            response = self.upload_file_via_http(screenshot_path, category='screenshots',
                                                      extra={'saved_from': 'background_job'},)
            self.send_to_server(1, f'Upload result: {response.text}', 0)
        finally:
            try:
                os.remove(screenshot_path)
            except Exception as e:
                self.send_to_server(0, f'Failed to remove temporary screenshot: {e}', 0)

    def run(self):
        try:
            time.sleep(2)
            self.mark_running()
            self.send_to_server(1, f'Scheduled screenshot task started (every {self.interval_seconds}s)', 0)

            schedule.every(self.interval_seconds).seconds.do(self._run_capture_task)

            while not self.stop_event.is_set():
                schedule.run_pending()
                time.sleep(1)

            self.send_to_server(1, 'Scheduled screenshot task stopped', 0)
        except Exception as e:
            self.send_to_server(0, f'Screenshot task error: {e}', 0)
        finally:
            schedule.clear()
            self.mark_stopped()
            logger.info(f'Thread ended: {threading.current_thread().name}')
            self.send_to_server(1, f'Task ended: {threading.current_thread().name}', 1)

    def stop(self, notify: bool = True):
        schedule.clear()
        self.request_stop(notify=notify)
