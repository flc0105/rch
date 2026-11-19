import hashlib
import json
import os
import re
import time
from datetime import datetime

from client.commands.platform.utils.ios_util import get_ios_contacts, get_ios_username
from client.commands.runtime.interrupts import timeout
from client.commands.shell.decorators import shell_command
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


class iOSShellCommands:
    """Shell commands backed by Pythonista and the iOS standard library."""

    @shell_command('List directory contents', group='shell')
    def ls(self, path='.'):
        try:
            target = os.path.expanduser((path or '.').strip())
            if not os.path.exists(target):
                return 0, f'Path not found: {target}'
            if not os.path.isdir(target):
                return 0, f'Not a directory: {target}'

            entries = []
            for name in os.listdir(target):
                full = os.path.join(target, name)
                is_dir = os.path.isdir(full)
                is_link = os.path.islink(full)
                display_name = f'{name}/' if is_dir else (f'{name}@' if is_link else name)
                entries.append((0 if is_dir else 1, name.lower(), display_name))

            entries.sort(key=lambda x: (x[0], x[1]))
            return 1, '\n'.join(item[2] for item in entries)
        except Exception as e:
            return 0, f'ls failed: {e}'

    @shell_command('Show current username', group='shell')
    def whoami(self):
        try:
            return 1, str(get_ios_username())
        except Exception as e:
            return 0, f'whoami failed: {e}'

    @shell_command('Create empty file', group='shell')
    def touch(self, path):
        try:
            target = os.path.expanduser((path or '').strip())
            if not target:
                return 0, 'Usage: touch <path>'

            parent = os.path.dirname(target)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)

            with open(target, 'a', encoding='utf-8'):
                os.utime(target, None)

            return 1, f'File touched: {target}'
        except Exception as e:
            return 0, f'touch failed: {e}'

    @shell_command('Read text file', group='shell')
    def cat(self, path):
        try:
            target = os.path.expanduser((path or '').strip())
            if not target:
                return 0, 'Usage: cat <file>'

            if not os.path.exists(target):
                return 0, f'Path not found: {target}'
            if not os.path.isfile(target):
                return 0, f'Not a file: {target}'

            with open(target, 'r', encoding='utf-8', errors='replace') as f:
                return 1, f.read()
        except Exception as e:
            return 0, f'cat failed: {e}'

    @shell_command('Compute file MD5', group='shell')
    def md5sum(self, path=''):
        try:
            target = os.path.expanduser((path or '').strip())
            if not target:
                return 0, 'Usage: md5sum <file>'
            if not os.path.exists(target):
                return 0, f'Path not found: {target}'
            if not os.path.isfile(target):
                return 0, f'Not a file: {target}'

            md5 = hashlib.md5()
            with open(target, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    md5.update(chunk)

            return 1, f'{md5.hexdigest()}  {target}'
        except Exception as e:
            return 0, f'md5sum failed: {e}'

    @shell_command('Print environment variables', group='shell')
    def printenv(self, name=''):
        try:
            key = (name or '').strip()
            if key:
                return 1, str(os.environ.get(key, ''))

            lines = []
            for env_name in sorted(os.environ.keys()):
                lines.append(f'{env_name}={os.environ.get(env_name, "")}')
            return 1, '\n'.join(lines)
        except Exception as e:
            return 0, f'printenv failed: {e}'

    @shell_command('Echo text or expand environment variables', group='shell')
    def echo(self, text=''):
        try:
            raw = str(text or '')

            rendered = re.sub(
                r'\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([^}]+)\}',
                lambda match: os.environ.get(match.group(1) or match.group(2) or '', ''),
                raw,
            )
            return 1, rendered
        except Exception as e:
            return 0, f'echo failed: {e}'

    @shell_command('Show system uptime', group='system')
    def uptime(self):
        try:
            from objc_util import ObjCClass

            seconds = max(0, float(ObjCClass('NSProcessInfo').processInfo().systemUptime()))
            boot_time = datetime.fromtimestamp(time.time() - seconds)
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            minutes = int((seconds % 3600) // 60)
            return 1, f"Boot time: {boot_time:%Y-%m-%d %H:%M:%S}\nUptime: {days}d {hours}h {minutes}m"
        except Exception as e:
            return 0, f'Failed to get system uptime: {e}'

    @shell_command('Read clipboard text', group='device')
    def clipboard_read(self):
        try:
            import clipboard
            return 1, clipboard.get() or ''
        except Exception as e:
            return 0, f'Failed to read clipboard: {e}'

    @shell_command('Write clipboard text', group='device')
    def clipboard_write(self, text=''):
        try:
            import clipboard
            clipboard.set(text or '')
            return 1, 'Clipboard updated'
        except Exception as e:
            return 0, f'Failed to write clipboard: {e}'

    @shell_command('Clear console output', group='console')
    def clear_console(self):
        try:
            import console
            console.clear()
            return 1, 'Console cleared'
        except Exception as e:
            return 0, f'Failed to clear console: {e}'

    @shell_command('Get current location', group='device')
    @timeout(15)
    def get_location(self):
        try:
            import location

            location.start_updates()
            try:
                self._checkpoint()
                time.sleep(1.5)
                self._checkpoint()
                data = location.get_location()
            finally:
                location.stop_updates()

            if not data:
                return 0, 'No location data'
            return 1, json.dumps(data, ensure_ascii=False)
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out'
        except Exception as exc:
            return 0, f'Failed to get location: {exc}'

    @shell_command('Speak text', group='device')
    def speak(self, text=''):
        try:
            import speech
            speech.say(text or '')
            return 1, 'Speech started'
        except Exception as e:
            return 0, f'Failed to speak text: {e}'

    @shell_command('List contacts via CNContactStore', group='device')
    def list_contacts(self, arg=''):
        if str(arg or '').strip():
            return 0, 'Usage: list_contacts'
        try:
            return 1, json.dumps(get_ios_contacts(), ensure_ascii=False, indent=2)
        except Exception as exc:
            return 0, f'Failed to list contacts: {exc}'

    @shell_command('List reminders', group='device')
    def list_reminders(self, arg=''):
        if str(arg or '').strip():
            return 0, 'Usage: list_reminders'
        try:
            import reminders

            rows = []
            for completed, status in ((False, 'Pending'), (True, 'Completed')):
                for reminder in reminders.get_reminders(completed=completed) or []:
                    alarms = []
                    for alarm in getattr(reminder, 'alarms', None) or []:
                        date = getattr(alarm, 'date', None)
                        alarms.append({
                            'date': date.isoformat() if date is not None else None,
                            'location': getattr(alarm, 'location', None),
                            'proximity': getattr(alarm, 'proximity', None),
                        })
                    due = getattr(reminder, 'due_date', None)
                    finished = getattr(reminder, 'completion_date', None)
                    rows.append({
                        'status': status,
                        'title': str(reminder.title or ''),
                        'notes': str(getattr(reminder, 'notes', None) or ''),
                        'dueDate': due.isoformat() if due is not None else None,
                        'completionDate': finished.isoformat() if finished is not None else None,
                        'priority': getattr(reminder, 'priority', None),
                        'url': str(getattr(reminder, 'url', None) or ''),
                        'alarms': alarms,
                    })
            return 1, json.dumps(rows, ensure_ascii=False, indent=2)
        except Exception as e:
            return 0, f'Failed to list reminders: {e}'

    @shell_command('Keep screen awake', group='console')
    def keep_awake(self, arg):
        import console
        if arg == 'on':
            console.set_idle_timer_disabled(True)
            return 1, 'Screen will stay awake'
        if arg == 'off':
            console.set_idle_timer_disabled(False)
            return 1, 'Screen sleep restored'
        return 0, 'keep_awake [on/off]'
