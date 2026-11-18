import json
import time
from datetime import datetime

from client.commands.platform.utils.ios_util import get_ios_username


class iOSSystemService:
    """
    iOS / Pythonista 系统信息能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def get_username(self):
        try:
            return 1, str(get_ios_username())
        except Exception as e:
            return 0, f'whoami failed: {e}'

    def get_uptime(self):
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

    def list_contacts(self):
        try:
            from client.commands.platform.utils.ios_util import get_ios_contacts

            result = get_ios_contacts()
            return 1, self.dump_json(result)
        except Exception as e:
            return 0, f'Failed to list contacts: {e}'

    def list_reminders(self):
        try:
            import reminders

            rows = []
            for completed, status in ((False, 'Pending'), (True, 'Completed')):
                for reminder in reminders.get_reminders(completed=completed) or []:
                    alarms = []
                    for alarm in getattr(reminder, 'alarms', None) or []:
                        alarms.append({
                            'date': self._reminder_date(getattr(alarm, 'date', None)),
                            'location': getattr(alarm, 'location', None),
                            'proximity': getattr(alarm, 'proximity', None),
                        })
                    rows.append({
                        'status': status,
                        'title': str(reminder.title or ''),
                        'notes': str(getattr(reminder, 'notes', None) or ''),
                        'dueDate': self._reminder_date(getattr(reminder, 'due_date', None)),
                        'completionDate': self._reminder_date(getattr(reminder, 'completion_date', None)),
                        'priority': getattr(reminder, 'priority', None),
                        'url': str(getattr(reminder, 'url', None) or ''),
                        'alarms': alarms,
                    })
            return 1, self.dump_json(rows)
        except Exception as e:
            return 0, f'Failed to list reminders: {e}'

    @staticmethod
    def _reminder_date(value):
        return value.isoformat() if value is not None else None

    def dump_json(self, payload):
        return json.dumps(payload, ensure_ascii=False, indent=2)
