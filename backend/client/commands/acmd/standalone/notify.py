"""Send a native local notification on the target Client."""
import logging
import subprocess
import time
from queue import Full, Queue
from threading import Lock, Thread

from client.commands.acmd.decorators import argument_command
from client.commands.platform.utils.mac_util import escape_osascript_text
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec


logger = logging.getLogger(__name__)
_windows_notifications = Queue(maxsize=32)
_windows_worker_lock = Lock()
_windows_worker = None


NOTIFY_SPEC = ArgumentCommandSpec(
    name='notify',
    description='Show a native notification on the Client',
    options=[
        ArgumentOptionSpec('title', 'str', default='', help_text='Notification title'),
        ArgumentOptionSpec('message', 'str', required=True, allow_empty=False, help_text='Notification message'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)


@argument_command('notify', spec=NOTIFY_SPEC, platforms=('mac', 'win', 'ios'))
def notify(self, args_dict):
    title = args_dict['title'].strip() or 'RCH'
    try:
        show = {'mac': _notify_mac, 'win': _notify_windows, 'ios': _notify_ios}
        result = show[self.command_platform](self, title, args_dict['message'])
        return 1, result or 'Notification requested.'
    except (OSError, RuntimeError, ImportError, ValueError, subprocess.SubprocessError) as exc:
        return 0, f'Could not send the notification: {exc}'


def _notify_mac(_owner, title, message):
    title = escape_osascript_text(title)
    message = escape_osascript_text(message)
    result = subprocess.run(
        ['osascript', '-e', f'display notification "{message}" with title "{title}"'],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'macOS rejected the notification')


def _notify_windows(_owner, title, message):
    import win32api
    import win32con
    import win32event
    import win32gui

    global _windows_worker
    with _windows_worker_lock:
        if _windows_worker is None or not _windows_worker.is_alive():
            _windows_worker = Thread(
                target=_run_windows_notifications,
                args=(win32api, win32con, win32event, win32gui),
                name='rch-windows-notifications',
                daemon=True,
            )
            _windows_worker.start()
        try:
            _windows_notifications.put_nowait((title, message))
        except Full as exc:
            raise RuntimeError('Windows notification queue is full. Try again shortly.') from exc
    return 'Notification queued.'


def _run_windows_notifications(win32api, win32con, win32event, win32gui):
    callback = win32con.WM_APP + 1
    # Shell delivers NIN_BALLOONHIDE / TIMEOUT / USERCLICK via the callback.
    finished_events = {win32con.WM_USER + offset for offset in (3, 4, 5)}
    finished = False

    def on_notification(_window, _message, _icon_id, event):
        nonlocal finished
        if event in finished_events:
            finished = True
        return 0

    window_class = win32gui.WNDCLASS()
    window_class.hInstance = win32api.GetModuleHandle(None)
    window_class.lpszClassName = 'RCH.LocalNotification'
    window_class.lpfnWndProc = {callback: on_notification}
    registered = False
    while True:
        title, message = _windows_notifications.get()
        hwnd = None
        icon_added = False
        finished = False
        try:
            if not registered:
                win32gui.RegisterClass(window_class)
                registered = True
            hwnd = win32gui.CreateWindowEx(
                0, window_class.lpszClassName, 'RCH', 0, 0, 0, 0, 0, 0, 0, window_class.hInstance, None,
            )
            icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            icon_flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_ADD, (hwnd, 1, icon_flags, callback, icon, 'RCH'),
            )
            icon_added = True
            # NOTIFYICONDATA has room for 63 and 255 UTF-16 units plus a terminator.
            info_title = title.encode('utf-16-le')[:126].decode('utf-16-le', errors='ignore')
            info = message.encode('utf-16-le')[:510].decode('utf-16-le', errors='ignore')
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_MODIFY,
                (hwnd, 1, win32gui.NIF_INFO, 0, 0, '', info, 0, info_title, win32gui.NIIF_INFO),
            )

            deadline = time.monotonic() + 30
            while not finished:
                win32gui.PumpWaitingMessages()
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if finished or remaining_ms <= 0:
                    break
                win32event.MsgWaitForMultipleObjects((), False, remaining_ms, win32event.QS_ALLINPUT)
        except Exception:
            logger.exception('Could not submit Windows notification')
        finally:
            try:
                if icon_added:
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 1))
            except Exception:
                logger.debug('Could not delete Windows notification icon', exc_info=True)
            try:
                if hwnd is not None:
                    win32gui.DestroyWindow(hwnd)
            except Exception:
                logger.debug('Could not destroy Windows notification window', exc_info=True)


def _notify_ios(owner, title, message):
    import notification

    notification.schedule(message, delay=0, title=title)
