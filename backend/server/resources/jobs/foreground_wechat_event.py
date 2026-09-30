import sys

import psutil

from client.jobs.core.job import Job
from client.runtime.sdk import events


JOB_METADATA = {
    'name': 'foreground_wechat_event',
    'display_name': 'Foreground WeChat Event',
    'description': 'Emit a Device Event when WeChat becomes the foreground application.',
    'platforms': ['win', 'mac'],
    'params': [
        {
            'name': 'interval',
            'type': 'number',
            'default': 0.5,
            'min': 0.2,
            'max': 10,
            'description': 'Polling interval in seconds.',
        },
    ],
}


def _windows_foreground_app() -> dict:
    import win32gui
    import win32process

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return {}
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process_name = ''
    try:
        process_name = psutil.Process(pid).name()
    except Exception:
        pass
    return {
        'pid': int(pid or 0),
        'process': process_name,
        'title': str(win32gui.GetWindowText(hwnd) or ''),
    }


def _macos_foreground_app() -> dict:
    # Prefer the same Quartz window-owner lookup used by the proven screenshot
    # monitor job: scan on-screen windows and use the first normal (layer 0)
    # window owner as the foreground application signal.
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
        )

        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
        )
        for window in windows or []:
            if window.get('kCGWindowLayer', 999) != 0:
                continue

            owner = str(window.get('kCGWindowOwnerName') or '').strip()
            if not owner:
                continue

            return {
                'pid': int(window.get('kCGWindowOwnerPID') or 0),
                'process': owner,
                'title': str(window.get('kCGWindowName') or ''),
            }
    except Exception:
        pass

    # Keep NSWorkspace as a fallback for macOS variants where the Quartz
    # window list is unavailable or temporarily returns no normal window.
    from AppKit import NSWorkspace

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return {}
    return {
        'pid': int(app.processIdentifier()),
        'process': str(app.localizedName() or ''),
        'bundle_id': str(app.bundleIdentifier() or ''),
        'title': str(app.localizedName() or ''),
    }


def _foreground_app() -> dict:
    if sys.platform == 'win32':
        return _windows_foreground_app()
    if sys.platform == 'darwin':
        return _macos_foreground_app()
    raise RuntimeError(f'Unsupported platform: {sys.platform}')


def _is_wechat(app: dict) -> bool:
    haystack = ' '.join([
        str(app.get('process') or ''),
        str(app.get('title') or ''),
        str(app.get('bundle_id') or ''),
    ]).lower()
    return any(token in haystack for token in ('wechat', 'weixin', '微信'))


class ForegroundWechatEvent(Job):
    def run(self):
        self.mark_running()
        failed = False
        interval = float(self.get_job_param('interval', 0.5) or 0.5)
        last_is_wechat = False

        try:
            while not self.stop_event.is_set():
                app = _foreground_app()
                is_wechat = _is_wechat(app)
                if is_wechat and not last_is_wechat:
                    try:
                        events.emit(
                            'app.foreground.wechat',
                            data=app,
                            message='WeChat became the foreground app',
                        )
                    except Exception as exc:
                        self.send_to_server(0, f'Device event emit failed: {exc}', 0)
                last_is_wechat = is_wechat
                self.stop_event.wait(interval)
        except Exception as exc:
            failed = True
            self.is_running = False
            self.stop_event.set()
            self._report_state('error', status=0, text=str(exc))
            self.send_to_server(0, f'Foreground WeChat watcher failed: {exc}', 1)
        finally:
            if not failed:
                self.mark_stopped()
