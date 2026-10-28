import json
import os
import time

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError
from core.utils.formatting import get_time


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

    def open_url(self, url):
        try:
            import webbrowser
            target = (url or '').strip()
            if not target:
                return 0, 'Usage: openurl <url>'
            ok = webbrowser.open(target)
            return 1, f'URL opened: {ok}'
        except Exception as e:
            return 0, f'Failed to open URL: {e}'

    def clear_console(self):
        try:
            import console
            console.clear()
            return 1, 'Console cleared'
        except Exception as e:
            return 0, f'Failed to clear console: {e}'

    def quick_look(self, path):
        try:
            import console

            target = os.path.expanduser((path or '').strip())
            if not target:
                return 0, 'Usage: quick_look <path>'
            if not os.path.exists(target):
                return 0, f'Path not found: {target}'

            console.quicklook(target)
            return 1, f'Preview opened: {target}'
        except Exception as e:
            return 0, f'Failed to preview file: {e}'

    def open_in(self, path):
        try:
            import console

            target = os.path.expanduser((path or '').strip())
            if not target:
                return 0, 'Usage: open_in <path>'
            if not os.path.exists(target):
                return 0, f'Path not found: {target}'

            console.open_in(target)
            return 1, f'Open In launched: {target}'
        except Exception as e:
            return 0, f'Failed to open file externally: {e}'

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

    def pick_upload(self, kind):
        try:
            import io
            import photos
            import dialogs

            kind = (kind or 'photo').strip().lower()

            form_data = self.owner.http_file_transfer_service.build_http_upload_form_data(
                artifact_type='files',
                category='download',
            )

            if kind == 'photo':
                image = photos.pick_image()
                if image is None:
                    return 0, 'No photo selected'

                buf = io.BytesIO()
                if image.mode not in ('RGB', 'L'):
                    image = image.convert('RGB')
                image.save(buf, format='JPEG', quality=90)
                buf.seek(0)

                response = self.owner.client_api.upload_file_source(
                    buf,
                    filename=f'photo_{get_time()}.png',
                    form_data=form_data,
                    timeout=30,
                )
            elif kind == 'file':
                file_path = dialogs.pick_document()
                if not file_path:
                    return 0, 'No file selected'

                response = self.owner.client_api.upload_file_source(
                    file_path,
                    filename=os.path.basename(file_path),
                    form_data=form_data,
                    timeout=30,
                )
            else:
                return 0, "kind must be 'photo' or 'file'"

            result = {
                'response_text': '',
                'status_code': response.status_code,
                'ok': response.ok,
            }

            try:
                result['response'] = response.json()
            except Exception:
                result['response_text'] = response.text

            return 1, json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return 0, f'Failed to pick/upload: {e}'

    def keep_awake(self, arg):
        import console
        if arg == 'on':
            console.set_idle_timer_disabled(True)
            return 1, 'Screen will stay awake'
        if arg == 'off':
            console.set_idle_timer_disabled(False)
            return 1, 'Screen sleep restored'
        return 0, 'keep_awake [on/off]'

    def kill_app(self):
        import os
        import time
        time.sleep(0.2)
        os._exit(0)
        return 1, ''

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