import time

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError


class iOSConsoleService:
    """
    iOS / Pythonista 控制台、剪贴板、系统交互能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def read_clipboard(self):
        try:
            import clipboard
            return 1, clipboard.get() or ''
        except Exception as e:
            return 0, f'Failed to read clipboard: {e}'

    def write_clipboard(self, text):
        try:
            import clipboard
            clipboard.set(text or '')
            return 1, 'Clipboard updated'
        except Exception as e:
            return 0, f'Failed to write clipboard: {e}'

    def clear_console(self):
        try:
            import console
            console.clear()
            return 1, 'Console cleared'
        except Exception as e:
            return 0, f'Failed to clear console: {e}'

    def get_location(self):
        try:
            import location

            location.start_updates()
            time.sleep(1.5)
            data = location.get_location()
            location.stop_updates()

            if not data:
                return 0, 'No location data'

            return 1, json.dumps(data, ensure_ascii=False)
        except CommandCancelledError:
            self.stop_location_updates()
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            self.stop_location_updates()
            return 0, 'Command timed out'
        except Exception as e:
            self.stop_location_updates()
            return 0, f'Failed to get location: {e}'

    def stop_location_updates(self):
        try:
            import location
            location.stop_updates()
        except Exception:
            pass

    def speak(self, text):
        try:
            import speech
            speech.say(text or '')
            return 1, 'Speech started'
        except Exception as e:
            return 0, f'Failed to speak text: {e}'

    def keep_awake(self, arg):
        import console
        if arg == 'on':
            console.set_idle_timer_disabled(True)
            return 1, 'Screen will stay awake'
        if arg == 'off':
            console.set_idle_timer_disabled(False)
            return 1, 'Screen sleep restored'
        return 0, 'keep_awake [on/off]'

    def acmd_alert(self, args_dict):
        try:
            title = args_dict.get('title', '')
            message = args_dict['message']
            import console
            button = console.alert(title or 'Alert', message or '', 'OK', hide_cancel_button=True)
            return 1, f'Alert closed: {button}'
        except Exception as e:
            return 0, f'Failed to show alert: {e}'

    def acmd_notify(self, args_dict):
        try:
            title = args_dict.get('title', '')
            message = args_dict['message']
            import notification
            notification.schedule(
                message or '',
                delay=0,
                sound_name=None,
                action_url=None,
                title=title or 'Notice'
            )
            return 1, 'Notification scheduled'
        except Exception as e:
            return 0, f'Failed to send notification: {e}'