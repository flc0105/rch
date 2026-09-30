import logging
import subprocess
import threading
import uuid


logger = logging.getLogger(__name__)


class MacOSNotificationBackend:
    """macOS notification backend for script-mode RCH Notifier.

    auto mode first tries UserNotifications.framework through PyObjC. Bare Python
    builds can be denied by macOS because notification authorization is app/bundle
    scoped, so auto mode falls back to the system osascript notification command.
    """

    def __init__(self, *, mode: str = 'auto', sound: bool = True):
        self.mode = str(mode or 'auto').strip().lower()
        self.sound = bool(sound)
        self._center = None
        self._un = None
        self.active_mode = ''

    def start(self):
        if self.mode in {'auto', 'usernotifications'}:
            try:
                self._start_usernotifications()
                self.active_mode = 'usernotifications'
                logger.info('macOS notification backend: UserNotifications.framework')
                return
            except Exception as exc:
                if self.mode == 'usernotifications':
                    raise
                logger.warning('UserNotifications unavailable; falling back to osascript: %s', exc)

        self._ensure_osascript()
        self.active_mode = 'osascript'
        logger.info('macOS notification backend: osascript fallback')

    def _start_usernotifications(self):
        import UserNotifications as UN

        center = UN.UNUserNotificationCenter.currentNotificationCenter()
        done = threading.Event()
        result = {'granted': False, 'error': None}

        def completed(granted, error):
            result['granted'] = bool(granted)
            result['error'] = error
            done.set()

        options = UN.UNAuthorizationOptionAlert
        if self.sound:
            options |= UN.UNAuthorizationOptionSound
        center.requestAuthorizationWithOptions_completionHandler_(options, completed)
        if not done.wait(12):
            raise RuntimeError('Timed out waiting for macOS notification authorization')
        if result['error'] is not None:
            raise RuntimeError(str(result['error']))
        if not result['granted']:
            raise RuntimeError('macOS notification permission was not granted')

        self._un = UN
        self._center = center

    @staticmethod
    def _ensure_osascript():
        result = subprocess.run(
            ['/usr/bin/which', 'osascript'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError('osascript is not available')

    def notify(self, notification: dict) -> bool:
        title = str((notification or {}).get('title') or 'RCH').strip() or 'RCH'
        message = str((notification or {}).get('message') or '').strip()
        if self.active_mode == 'usernotifications':
            try:
                return self._notify_usernotifications(title, message)
            except Exception as exc:
                if self.mode != 'auto':
                    raise
                logger.warning('UserNotifications delivery failed; switching to osascript: %s', exc)
                self._ensure_osascript()
                self.active_mode = 'osascript'
        return self._notify_osascript(title, message)

    def _notify_usernotifications(self, title: str, message: str) -> bool:
        UN = self._un
        content = UN.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(message)
        if self.sound:
            content.setSound_(UN.UNNotificationSound.defaultSound())

        request = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(
            uuid.uuid4().hex,
            content,
            None,
        )
        done = threading.Event()
        result = {'error': None}

        def completed(error):
            result['error'] = error
            done.set()

        self._center.addNotificationRequest_withCompletionHandler_(request, completed)
        # Some PyObjC/Python builds do not immediately dispatch the completion
        # block without a full application run loop. Treat an async timeout as
        # accepted; explicit errors still trigger the reliable fallback.
        if done.wait(2) and result['error'] is not None:
            raise RuntimeError(str(result['error']))
        return True

    def _notify_osascript(self, title: str, message: str) -> bool:
        script = (
            'on run argv\n'
            'set notificationTitle to item 1 of argv\n'
            'set notificationBody to item 2 of argv\n'
        )
        if self.sound:
            script += 'display notification notificationBody with title notificationTitle sound name "default"\n'
        else:
            script += 'display notification notificationBody with title notificationTitle\n'
        script += 'end run\n'

        result = subprocess.run(
            ['/usr/bin/osascript', '-e', script, title, message],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or 'osascript notification failed').strip())
        return True
