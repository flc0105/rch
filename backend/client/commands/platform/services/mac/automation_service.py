import os
import re
import shlex
import subprocess
import tempfile

from client.runtime.client_util import get_executable_path, get_runtime_root


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
        """Authorize once, start the real Client command and report its PID."""
        command = get_executable_path()
        if detached:
            # macOS has setsid(2), but not a guaranteed setsid(1) command.
            # The built-in Perl launcher calls setsid then execs the Client,
            # preserving the PID without modifying rchclient's argv.
            launcher = 'setsid() != -1 or die "setsid failed: $!"; exec @ARGV or die "exec failed: $!";'
            command = f'/usr/bin/perl -MPOSIX=setsid -e {shlex.quote(launcher)} -- {command}'

        log_fd, log_path = tempfile.mkstemp(prefix='rch-elevated-', suffix='.log')
        os.close(log_fd)
        log_file = shlex.quote(log_path)
        script = (
            f'cd {shlex.quote(get_runtime_root())} || exit 1; '
            f'{command} </dev/null >>{log_file} 2>&1 & '
            'rch_pid=$!; sleep 1; '
            'if kill -0 "$rch_pid" 2>/dev/null; then '
            'printf "RCH_ELEVATED_CLIENT_PID=%s\\n" "$rch_pid"; '
            f'printf "RCH_ELEVATED_CLIENT_LOG=%s\\n" {log_file}; '
            'else '
            f'tail -c 3000 {log_file} 2>/dev/null; '
            'exit 1; fi'
        )
        applescript = (
            f'do shell script "{self.escape_osascript_text(script)}" '
            'with administrator privileges'
        )
        try:
            result = subprocess.run(
                ['osascript', '-e', applescript], capture_output=True,
                text=True, timeout=120, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 0, f'Elevated Client launch failed: {exc} (startup log: {log_path})'
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip()
            return 0, f'Elevated Client launch failed: {detail or f"osascript exited {result.returncode}"} (startup log: {log_path})'
        match = re.search(r'RCH_ELEVATED_CLIENT_PID=(\d+)', result.stdout or '')
        if not match:
            return 0, f'Elevated Client launch failed: no Client PID (startup log: {log_path})'
        return 1, (
            f'Elevated Client process started (PID: {int(match.group(1))}) '
            f'(startup stderr: {log_path}); connection not yet verified'
        )

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
