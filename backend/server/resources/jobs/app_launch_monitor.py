JOB_METADATA = {
    "name": "app_launch_monitor",
    "display_name": "App Launch Monitor",
    "description": "Monitor app launch activity on macOS",
    "platforms": ["darwin"],
    "params": [
        {
            "name": "interval_seconds",
            "type": "integer",
            "required": False,
            "default": 2,
            "min": 1,
            "description": "Polling interval in seconds"
        },
        {
            "name": "target_apps_csv",
            "type": "string",
            "required": False,
            "default": "",
            "description": "Comma-separated app names; empty means monitor all"
        }
    ]
}

import os
import threading
import time

from client.jobs.job import Job
from core.utils.logger import logger


class AppLaunchMonitor(Job):
    def __init__(self, target_apps=None, interval=2):
        """
        应用启动监控器

        :param target_apps: 要监控的应用列表，None 表示监控所有应用
        :param interval: 检查间隔（秒）
        """
        super().__init__()
        self.target_apps = target_apps
        self.interval = interval
        self.running_apps = {}  # 记录当前运行的应用 {pid: {name, exe, windows}}
        self.initial_snapshot_sent = False

    def on_context_bound(self):
        self.interval = int(self.get_job_param('interval_seconds', 2) or 2)
        raw = str(self.get_job_param('target_apps_csv', '') or '').strip()
        items = [item.strip() for item in raw.split(',') if item.strip()]
        self.target_apps = items or None

    def run(self):
        try:
            time.sleep(2)
            self.send_to_server(1, 'App launch monitor started', 0)

            try:
                from Quartz import (
                    CGWindowListCopyWindowInfo,
                    kCGWindowListOptionAll,
                    kCGNullWindowID
                )
            except ImportError:
                self.send_to_server(0, 'Quartz not available, install: pip install pyobjc-framework-Quartz', 0)
                self.mark_stopped()
                return

            self.mark_running()
            self.send_to_server(1, f'Monitoring apps (interval: {self.interval}s)', 0)
            if self.target_apps:
                self.send_to_server(1, f'Target apps: {", ".join(self.target_apps)}', 0)

            while not self.stop_event.is_set():
                self._check_app_changes()
                time.sleep(self.interval)

            self.send_to_server(1, 'App launch monitor stopped', 0)
        except Exception as e:
            self.send_to_server(0, f'App launch monitor error: {e}', 0)
        finally:
            self.mark_stopped()
            logger.info(f'Thread ended: {threading.current_thread().name}')
            self.send_to_server(1, f'Task ended: {threading.current_thread().name}', 1)

    def stop(self, notify: bool = True):
        self.request_stop(notify=notify)

    def _is_system_process(self, app_name, exe_path):
        """判断是否为系统进程"""
        system_paths = [
            '/System/',
            '/usr/libexec/',
            '/usr/bin/',
            '/usr/sbin/',
            '/bin/',
            '/sbin/',
            '/Library/CoreServices/',
            '/System/Library/'
        ]

        system_names = [
            'WindowServer', 'kernel_task', 'launchd', 'loginwindow',
            'SystemUIServer', 'Dock', 'Finder', 'NotificationCenter',
            'Spotlight', 'coreaudiod', 'blued', 'distnoted', 'cfprefsd',
            'powerd', 'securityd', 'syslogd', 'usbd', 'warmd', 'mDNSResponder'
        ]

        for sys_path in system_paths:
            if exe_path.startswith(sys_path):
                return True

        for sys_name in system_names:
            if app_name == sys_name:
                return True

        if not exe_path.endswith('.app/Contents/MacOS/') and '.app' not in exe_path:
            return True

        return False

    def _get_app_exe_path(self, pid):
        """获取应用路径"""
        try:
            import psutil
            proc = psutil.Process(pid)
            return proc.exe() if os.path.exists(proc.exe()) else ''
        except:
            return ''

    def _get_all_apps_info(self):
        """获取所有运行中的应用信息（PID, 名称, 窗口）"""
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionAll,
                kCGNullWindowID
            )

            windows = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)
            apps = {}

            for window in windows:
                pid = window.get('kCGWindowOwnerPID', 0)
                if pid == 0:
                    continue

                app_name = window.get('kCGWindowOwnerName', '')
                if not app_name:
                    continue

                title = window.get('kCGWindowName', '')
                if not title:
                    continue

                if pid not in apps:
                    apps[pid] = {
                        'pid': pid,
                        'name': app_name,
                        'windows': []
                    }

                if title and title not in apps[pid]['windows']:
                    apps[pid]['windows'].append(title)

            return apps
        except Exception as e:
            return {}

    def _should_monitor(self, app_name):
        """判断是否需要监控该应用"""
        if not self.target_apps:
            return True

        for target in self.target_apps:
            if target.lower() in app_name.lower():
                return True
        return False

    def _send_app_info(self, app_info, is_initial=False):
        """发送应用信息"""
        prefix = "[Current] " if is_initial else ""

        message_lines = []
        message_lines.append(f"{prefix}{app_info['name']} (PID: {app_info['pid']})")

        if app_info.get('exe'):
            message_lines.append(f"  Path: {app_info['exe']}")

        if app_info.get('windows'):
            windows_str = ', '.join(app_info['windows'][:3])
            if len(app_info['windows']) > 3:
                windows_str += f' (+{len(app_info["windows"]) - 3} more)'
            message_lines.append(f"  Windows: {windows_str}")

        self.send_to_server(1, '\n'.join(message_lines), 0)

    def _check_app_changes(self):
        """检查应用变化 - 只基于 PID 判断新启动和退出"""
        try:
            current_apps = self._get_all_apps_info()
            current_pids = set(current_apps.keys())
            previous_pids = set(self.running_apps.keys())

            # 首次运行，发送当前所有运行中的应用
            if not self.initial_snapshot_sent:
                self.send_to_server(1, '--- Currently running applications ---', 0)

                for pid, app_info in current_apps.items():
                    # 获取应用路径
                    exe = self._get_app_exe_path(pid)
                    app_info['exe'] = exe

                    # 过滤系统进程
                    if self._is_system_process(app_info['name'], exe):
                        continue

                    if not self._should_monitor(app_info['name']):
                        continue

                    self._send_app_info(app_info, is_initial=True)
                    self.running_apps[pid] = app_info

                if not current_pids:
                    self.send_to_server(1, 'No applications running', 0)

                self.send_to_server(1, '--- Monitoring for new apps ---', 0)
                self.initial_snapshot_sent = True
                return

            # 新启动的应用（PID 不在之前记录中）
            new_pids = current_pids - previous_pids

            for pid in new_pids:
                app_info = current_apps[pid]

                # 获取应用路径
                exe = self._get_app_exe_path(pid)
                app_info['exe'] = exe

                # 过滤系统进程
                if self._is_system_process(app_info['name'], exe):
                    continue

                if not self._should_monitor(app_info['name']):
                    continue

                self._send_app_info(app_info, is_initial=False)
                self.running_apps[pid] = app_info

            # 应用退出（PID 在之前记录中但不在当前）
            exited_pids = previous_pids - current_pids
            for pid in exited_pids:
                if pid in self.running_apps:
                    app_name = self.running_apps[pid].get('name', 'Unknown')
                    if self._should_monitor(app_name):
                        self.send_to_server(1, f'App exited: {app_name} (PID: {pid})', 0)
                    del self.running_apps[pid]

            # 注意：不处理窗口变化，避免重复通知

        except Exception as e:
            self.send_to_server(0, f'Check error: {e}', 0)