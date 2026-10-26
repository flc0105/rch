import subprocess

from client.runtime.client_util import get_executable_path


class MacAutomationService:
    """
    macOS AppleScript / osascript / 权限交互能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def escape_osascript_text(self, value: str):
        text = str(value or '')
        text = text.replace('\\', '\\\\')
        text = text.replace('"', '\\"')
        return text

    def spawn_osascript(self, applescript: str):
        process = subprocess.Popen(
            ['osascript', '-e', applescript],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        self.owner._register_cancel_handler(lambda: self.owner._terminate_process(process))
        return process

    def sudo_self(self, *, detached=False):
        """以 root 权限启动新实例，返回 PID。"""
        cmd = get_executable_path()
        if detached:
            cmd = f'{cmd} --elevated-detached-bootstrap'

        popen_kwargs = {
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
        }
        if detached:
            popen_kwargs.update({
                'stdin': subprocess.DEVNULL,
                'start_new_session': True,
            })

        # 默认模式保持原有生命周期；--detached 只让提权进程充当短生命周期 bootstrap。
        proc = subprocess.Popen(
            ['osascript', '-e', f'do shell script "{cmd}" with administrator privileges'],
            **popen_kwargs,
        )

        if detached:
            return 1, f'New detached instance launch requested with sudo (bootstrap PID: {proc.pid})'
        return 1, f'New instance launched with sudo (parent PID: {proc.pid})'

    def sudo_run(self, command):
        """以 root 权限执行命令 (macOS)"""
        try:
            result = subprocess.run(
                ['osascript', '-e', f'do shell script "{command}" with administrator privileges'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return 1, result.stdout
            return 0, result.stderr
        except Exception as e:
            return 0, f'Failed: {e}'

    def acmd_msgbox(self, args_dict, payload=None):
        try:
            title = args_dict.get('title', '')
            text = args_dict['text']
            timeout = args_dict.get('timeout')

            escaped_text = self.escape_osascript_text(text)
            escaped_title = self.escape_osascript_text(title)

            applescript = (
                f'display dialog "{escaped_text}" '
                f'with title "{escaped_title}" buttons {{"OK"}} default button "OK"'
            )
            if timeout is not None and timeout > 0:
                applescript += f' giving up after {timeout}'

            process = self.spawn_osascript(applescript)
            return 1, f'Message box launched asynchronously: {title or "(no title)"}\nPID: {process.pid}'
        except Exception as e:
            return 0, f'Failed to launch message box: {e}'

    def acmd_notify(self, args_dict, payload=None):
        try:
            title = args_dict.get('title', '')
            text = args_dict['text']
            sound = args_dict.get('sound', False)

            escaped_text = self.escape_osascript_text(text)
            escaped_title = self.escape_osascript_text(title)

            applescript = f'display notification "{escaped_text}"'
            if escaped_title:
                applescript += f' with title "{escaped_title}"'
            if sound:
                applescript += ' sound name "default"'

            process = self.spawn_osascript(applescript)
            return 1, f'Notification launched asynchronously: {title or "(no title)"}\nPID: {process.pid}'
        except Exception as e:
            return 0, f'Failed to launch notification: {e}'
