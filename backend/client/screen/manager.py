import base64
import threading
import time

from core.device.local_identity import get_local_identity
from core.protocol.screen import (
    SCREEN_DEFAULT_FPS,
    SCREEN_MAX_FPS,
    SCREEN_MAX_QUALITY,
    SCREEN_MIN_FPS,
    SCREEN_MIN_QUALITY,
    normalize_screen_fps,
    normalize_screen_quality,
)
from client.screen.frame_strategies.factory import build_screen_frame_strategy
from core.protocol.message_types import (
    MSG_TYPE_SCREEN_CLOSED,
    MSG_TYPE_SCREEN_ERROR,
    MSG_TYPE_SCREEN_FRAME,
    MSG_TYPE_SCREEN_INPUT_ERROR,
    MSG_TYPE_SCREEN_OPENED,
)
from core.utils.logger import logger


class ScreenViewManager:
    """
    Client 端只读屏幕预览管理器。

    负责截图、帧传输与可选鼠标/键盘输入通道。
    平台相关行为统一使用本机 identity，而不是在各方法重复判断 sys.platform。
    """

    MIN_FPS = SCREEN_MIN_FPS
    MAX_FPS = SCREEN_MAX_FPS
    MIN_QUALITY = SCREEN_MIN_QUALITY
    MAX_QUALITY = SCREEN_MAX_QUALITY
    INPUT_BUTTONS = {'left', 'middle', 'right'}

    def __init__(self, connection):
        self.connection = connection
        self._os_alias = get_local_identity().os_alias
        self._lock = threading.RLock()
        self._input_lock = threading.RLock()
        self._sessions = {}
        self._windows_input_guard = None

    def open_session(self, screen_session_id: str, fps: int = SCREEN_DEFAULT_FPS, quality: int = 60):
        session_id = str(screen_session_id or '').strip()
        if not session_id:
            return False

        self.close_session(session_id, notify=False)
        frame_strategy = build_screen_frame_strategy()

        item = {
            'screen_session_id': session_id,
            'fps': normalize_screen_fps(fps),
            'quality': normalize_screen_quality(quality),
            'frame_strategy': frame_strategy,
            'frame_strategy_name': frame_strategy.name,
            'stop_event': threading.Event(),
            'notify_on_close': True,
            'thread': None,
            'frame_width': 0,
            'frame_height': 0,
            'origin_x': 0,
            'origin_y': 0,
            'input_width': 0,
            'input_height': 0,
            'input_origin_x': 0,
            'input_origin_y': 0,
            'pressed_keys': set(),
            'pressed_buttons': set(),
            'pyautogui_failsafe': None,
        }

        worker = threading.Thread(
            target=self._capture_loop,
            args=(session_id,),
            daemon=True,
            name=f'screen-view-{session_id[:8]}',
        )
        item['thread'] = worker

        with self._lock:
            self._sessions[session_id] = item

        self.connection.send({
            'type': MSG_TYPE_SCREEN_OPENED,
            'screen_session_id': session_id,
            'fps': item['fps'],
            'quality': item['quality'],
            'frame_strategy': item['frame_strategy_name'],
        })
        worker.start()
        return True

    def update_session(self, screen_session_id: str, fps=None, quality=None):
        session_id = str(screen_session_id or '').strip()
        with self._lock:
            item = self._sessions.get(session_id)
            if not item:
                return False
            if fps is not None:
                item['fps'] = normalize_screen_fps(fps)
            if quality is not None:
                item['quality'] = normalize_screen_quality(quality)
        return True

    def close_session(self, screen_session_id: str, notify: bool = True):
        session_id = str(screen_session_id or '').strip()
        with self._lock:
            item = self._sessions.get(session_id)
            if not item:
                return False
            item['notify_on_close'] = bool(notify)
            item['stop_event'].set()

        self._release_session_inputs(item, restore_control=True)
        return True

    def close_all_sessions(self, notify: bool = True):
        with self._lock:
            session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            self.close_session(session_id, notify=notify)

    def handle_input(self, screen_session_id: str, event: dict):
        session_id = str(screen_session_id or '').strip()
        with self._lock:
            item = self._sessions.get(session_id)
        if not item:
            return False

        payload = event if isinstance(event, dict) else {}
        action = str(payload.get('action') or '').strip().lower()
        if not action:
            return False

        try:
            with self._input_lock:
                self._apply_input_event(item, action, payload)
            return True
        except Exception as e:
            logger.warning(f'Screen control input failed: {e}', exc_info=True)
            self._release_session_inputs(item, restore_control=True)
            self._send_input_error(session_id, str(e or 'Screen control input failed'))
            return False

    def _capture_loop(self, screen_session_id: str):
        failed = False
        try:
            while True:
                with self._lock:
                    item = self._sessions.get(screen_session_id)
                    if not item:
                        return
                    stop_event = item['stop_event']
                    fps = item['fps']
                    quality = item['quality']
                    frame_strategy = item['frame_strategy']

                if stop_event.is_set():
                    break

                started_at = time.monotonic()
                image = self._capture_image()
                frame = frame_strategy.encode(image, quality)
                origin_x, origin_y = self._capture_origin(image)
                width = int(image.width)
                height = int(image.height)

                with self._lock:
                    current = self._sessions.get(screen_session_id)
                    if current:
                        current['frame_width'] = int(width)
                        current['frame_height'] = int(height)
                        current['origin_x'] = int(origin_x)
                        current['origin_y'] = int(origin_y)

                if frame:
                    frame_bytes = frame['data']
                    self.connection.send({
                        'type': MSG_TYPE_SCREEN_FRAME,
                        'screen_session_id': screen_session_id,
                        'frame_strategy': frame['strategy'],
                        'frame_type': frame['frame_type'],
                        'frame_seq': int(frame['frame_seq']),
                        'base_seq': int(frame['base_seq']),
                        'data': base64.b64encode(frame_bytes).decode('ascii'),
                        'width': int(frame['width']),
                        'height': int(frame['height']),
                        'patch_x': int(frame['patch_x']),
                        'patch_y': int(frame['patch_y']),
                        'patch_width': int(frame['patch_width']),
                        'patch_height': int(frame['patch_height']),
                        'bytes': len(frame_bytes),
                        'captured_at': time.time(),
                    })

                elapsed = time.monotonic() - started_at
                delay = max(0.0, (1.0 / max(1, fps)) - elapsed)
                if stop_event.wait(delay):
                    break
        except Exception as e:
            failed = True
            logger.error(f'Screen view capture failed: {e}', exc_info=True)
            try:
                self.connection.send({
                    'type': MSG_TYPE_SCREEN_ERROR,
                    'screen_session_id': screen_session_id,
                    'message': str(e or 'Screen capture failed'),
                })
            except Exception:
                pass
        finally:
            notify = False
            with self._lock:
                item = self._sessions.pop(screen_session_id, None)
                if item:
                    notify = bool(item.get('notify_on_close'))

            if item:
                self._release_session_inputs(item, restore_control=True)

            if notify and not failed:
                try:
                    self.connection.send({
                        'type': MSG_TYPE_SCREEN_CLOSED,
                        'screen_session_id': screen_session_id,
                    })
                except Exception:
                    pass

    def _apply_input_event(self, item: dict, action: str, payload: dict):
        if action == 'prepare':
            self._ensure_windows_input_allowed(action)
            pyautogui = self._get_pyautogui()

            # 截图像素尺寸和系统输入坐标尺寸不一定相同。macOS Retina 与
            # Windows DPI 缩放都会出现这种情况，因此控制开启时单独记录
            # 输入坐标空间，鼠标位置仍通过归一化坐标映射，协议无需变化。
            if self._os_alias == 'mac':
                input_width, input_height = pyautogui.size()
                item['input_width'] = int(input_width)
                item['input_height'] = int(input_height)
                item['input_origin_x'] = 0
                item['input_origin_y'] = 0
            elif self._os_alias == 'win':
                origin_x, origin_y, input_width, input_height = self._get_windows_input_geometry(pyautogui)
                item['input_width'] = int(input_width)
                item['input_height'] = int(input_height)
                item['input_origin_x'] = int(origin_x)
                item['input_origin_y'] = int(origin_y)

            if item.get('pyautogui_failsafe') is None:
                item['pyautogui_failsafe'] = bool(getattr(pyautogui, 'FAILSAFE', True))
                pyautogui.FAILSAFE = False
            return

        if action == 'release_all':
            self._release_session_inputs(item)
            return

        if action == 'control_off':
            self._release_session_inputs(item, restore_control=True)
            return

        pyautogui = self._get_pyautogui()

        if action == 'mouse_move':
            x, y = self._resolve_pointer(item, payload)
            self._ensure_windows_input_allowed(action, x=x, y=y)
            if self._os_alias == 'win':
                try:
                    self._send_windows_mouse_move(item, x, y)
                except Exception as e:
                    # Keep the old SetCursorPos-backed path as a best-effort
                    # fallback, but prefer SendInput so Windows shell hover
                    # tracking sees a synthesized mouse-move input event.
                    logger.debug(f'Windows SendInput mouse move failed, falling back: {e}')
                    pyautogui.moveTo(x, y, duration=0, _pause=False)
            else:
                pyautogui.moveTo(x, y, duration=0, _pause=False)
            return

        if action in ('mouse_down', 'mouse_up'):
            button = self._normalize_button(payload.get('button'))
            x, y = self._resolve_pointer(item, payload)
            self._ensure_windows_input_allowed(action, x=x, y=y)
            if action == 'mouse_down':
                pyautogui.mouseDown(x=x, y=y, button=button, _pause=False)
                item['pressed_buttons'].add(button)
            else:
                pyautogui.mouseUp(x=x, y=y, button=button, _pause=False)
                item['pressed_buttons'].discard(button)
            return

        if action == 'mouse_wheel':
            clicks = self._normalize_wheel(payload.get('delta'))
            if not clicks:
                return
            x, y = self._resolve_pointer(item, payload)
            self._ensure_windows_input_allowed(action, x=x, y=y)
            pyautogui.moveTo(x, y, duration=0, _pause=False)
            if self._os_alias == 'win':
                # Win32 一格滚轮需要 WHEEL_DELTA(120)，绕过 PyAutoGUI Windows 的原始 delta 注入问题。
                import win32api
                import win32con
                win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, clicks * win32con.WHEEL_DELTA, 0)
            else:
                pyautogui.scroll(clicks, _pause=False)
            return

        if action in ('key_down', 'key_up'):
            key = self._normalize_key(payload.get('key'))
            if not key:
                return
            self._ensure_windows_input_allowed(action)
            if action == 'key_down':
                is_repeat = bool(payload.get('repeat'))
                if key in item['pressed_keys']:
                    # 浏览器长按会持续发送 repeat keydown；modifier 不需要重复注入。
                    if is_repeat and not self._is_modifier_key(key):
                        pyautogui.keyDown(key, _pause=False)
                    return
                pyautogui.keyDown(key, _pause=False)
                item['pressed_keys'].add(key)
            else:
                pyautogui.keyUp(key, _pause=False)
                item['pressed_keys'].discard(key)
            return

        raise ValueError(f'Unsupported screen input action: {action}')

    def _release_session_inputs(self, item: dict, restore_control: bool = False):
        if not item:
            return

        with self._input_lock:
            pressed_keys = list(item.get('pressed_keys') or set())
            pressed_buttons = list(item.get('pressed_buttons') or set())
            item.get('pressed_keys', set()).clear()
            item.get('pressed_buttons', set()).clear()

            needs_restore = restore_control and item.get('pyautogui_failsafe') is not None
            if not pressed_keys and not pressed_buttons and not needs_restore:
                return

            try:
                pyautogui = self._get_pyautogui()
            except Exception:
                if restore_control:
                    item['pyautogui_failsafe'] = None
                return

            for key in reversed(pressed_keys):
                try:
                    pyautogui.keyUp(key, _pause=False)
                except Exception:
                    pass
            for button in pressed_buttons:
                try:
                    pyautogui.mouseUp(button=button, _pause=False)
                except Exception:
                    pass

            if restore_control:
                previous_failsafe = item.get('pyautogui_failsafe')
                if previous_failsafe is not None:
                    try:
                        pyautogui.FAILSAFE = bool(previous_failsafe)
                    except Exception:
                        pass
                    item['pyautogui_failsafe'] = None

    def _resolve_pointer(self, item: dict, payload: dict):
        width = int(item.get('frame_width') or 0)
        height = int(item.get('frame_height') or 0)
        origin_x = int(item.get('origin_x') or 0)
        origin_y = int(item.get('origin_y') or 0)

        if self._os_alias == 'mac':
            width = int(item.get('input_width') or 0)
            height = int(item.get('input_height') or 0)
            origin_x = int(item.get('input_origin_x') or 0)
            origin_y = int(item.get('input_origin_y') or 0)

            if width <= 0 or height <= 0:
                try:
                    width, height = self._get_pyautogui().size()
                    width = int(width)
                    height = int(height)
                except Exception as e:
                    raise RuntimeError(
                        f'Unable to resolve macOS input geometry: {e}'
                    ) from e
        elif self._os_alias == 'win':
            width = int(item.get('input_width') or 0)
            height = int(item.get('input_height') or 0)
            origin_x = int(item.get('input_origin_x') or 0)
            origin_y = int(item.get('input_origin_y') or 0)

            if width <= 0 or height <= 0:
                try:
                    origin_x, origin_y, width, height = self._get_windows_input_geometry(
                        self._get_pyautogui()
                    )
                except Exception as e:
                    raise RuntimeError(
                        f'Unable to resolve Windows input geometry: {e}'
                    ) from e

        if width <= 0 or height <= 0:
            raise RuntimeError('Screen input geometry is not ready')

        try:
            normalized_x = float(payload.get('x'))
            normalized_y = float(payload.get('y'))
        except Exception as e:
            raise ValueError('Invalid screen pointer coordinates') from e

        normalized_x = max(0.0, min(1.0, normalized_x))
        normalized_y = max(0.0, min(1.0, normalized_y))

        x = origin_x + int(round(normalized_x * max(0, width - 1)))
        y = origin_y + int(round(normalized_y * max(0, height - 1)))

        return x, y

    @staticmethod
    def _get_windows_input_geometry(pyautogui):
        try:
            import ctypes

            user32 = ctypes.windll.user32
            origin_x = int(user32.GetSystemMetrics(76))
            origin_y = int(user32.GetSystemMetrics(77))
            width = int(user32.GetSystemMetrics(78))
            height = int(user32.GetSystemMetrics(79))
            if width > 0 and height > 0:
                return origin_x, origin_y, width, height
        except Exception:
            pass

        width, height = pyautogui.size()
        return 0, 0, int(width), int(height)

    @staticmethod
    def _normalize_windows_absolute_pointer(value: int, origin: int, size: int) -> int:
        size = int(size or 0)
        if size <= 1:
            return 0
        relative = int(value) - int(origin)
        normalized = int(round((relative * 65535) / (size - 1)))
        return max(0, min(65535, normalized))

    def _send_windows_mouse_move(self, item: dict, x: int, y: int):
        """Inject a Windows mouse-move event across the virtual desktop.

        PyAutoGUI's Windows move path calls SetCursorPos(), which moves the
        cursor but is not equivalent to an injected mouse input stream.  Shell
        UI such as taskbar thumbnail hover tracking behaves more like local/VNC
        input when the move is sent through SendInput.
        """
        import ctypes
        from ctypes import wintypes

        origin_x = int(item.get('input_origin_x') or 0)
        origin_y = int(item.get('input_origin_y') or 0)
        width = int(item.get('input_width') or 0)
        height = int(item.get('input_height') or 0)
        if width <= 0 or height <= 0:
            origin_x, origin_y, width, height = self._get_windows_input_geometry(
                self._get_pyautogui()
            )

        dx = self._normalize_windows_absolute_pointer(x, origin_x, width)
        dy = self._normalize_windows_absolute_pointer(y, origin_y, height)

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ('dx', wintypes.LONG),
                ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_size_t),
            ]

        class Input(ctypes.Structure):
            _fields_ = [
                ('type', wintypes.DWORD),
                ('mi', MouseInput),
            ]

        mouseeventf_move = 0x0001
        mouseeventf_move_nocoalesce = 0x2000
        mouseeventf_virtualdesk = 0x4000
        mouseeventf_absolute = 0x8000
        input_mouse = 0

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT

        event = Input(
            type=input_mouse,
            mi=MouseInput(
                dx=dx,
                dy=dy,
                mouseData=0,
                dwFlags=(
                    mouseeventf_move
                    | mouseeventf_move_nocoalesce
                    | mouseeventf_virtualdesk
                    | mouseeventf_absolute
                ),
                time=0,
                dwExtraInfo=0,
            ),
        )
        ctypes.set_last_error(0)
        sent = int(user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)))
        if sent != 1:
            error = ctypes.get_last_error()
            raise OSError(error, 'SendInput mouse move failed')

    def _ensure_windows_input_allowed(self, action: str, x=None, y=None):
        if self._os_alias != 'win':
            return

        if self._windows_input_guard is None:
            from client.screen.windows_input_guard import WindowsScreenInputGuard
            self._windows_input_guard = WindowsScreenInputGuard()

        self._windows_input_guard.ensure_allowed(action=action, x=x, y=y)

    def _get_pyautogui(self):
        try:
            import pyautogui
            return pyautogui
        except Exception as e:
            raise RuntimeError(f'pyautogui is unavailable for screen control: {e}') from e

    def _normalize_button(self, value) -> str:
        button = str(value or '').strip().lower()
        if button not in self.INPUT_BUTTONS:
            raise ValueError(f'Unsupported mouse button: {button or value}')
        return button

    def _normalize_wheel(self, value) -> int:
        try:
            clicks = int(value)
        except Exception:
            clicks = 0
        return max(-10, min(10, clicks))

    def _is_modifier_key(self, key: str) -> bool:
        return key in {'ctrl', 'shift', 'alt', 'command', 'win'}

    def _normalize_key(self, value) -> str:
        key = str(value or '').strip().lower()
        if not key:
            return ''
        if key == 'meta':
            if self._os_alias == 'mac':
                return 'command'
            return 'win'
        aliases = {
            'control': 'ctrl',
            'escape': 'esc',
            'arrowup': 'up',
            'arrowdown': 'down',
            'arrowleft': 'left',
            'arrowright': 'right',
            'pageup': 'pgup',
            'pagedown': 'pgdn',
            'capslock': 'capslock',
            'numlock': 'numlock',
            'scrolllock': 'scrolllock',
            'printscreen': 'printscreen',
        }
        return aliases.get(key, key)

    def _send_input_error(self, screen_session_id: str, message: str):
        try:
            self.connection.send({
                'type': MSG_TYPE_SCREEN_INPUT_ERROR,
                'screen_session_id': screen_session_id,
                'message': str(message or 'Screen control input failed'),
            })
        except Exception:
            pass

    def _capture_image(self):
        image_grab_error = None
        try:
            from PIL import ImageGrab
            try:
                return ImageGrab.grab(all_screens=True)
            except TypeError:
                return ImageGrab.grab()
        except Exception as e:
            image_grab_error = e

        try:
            import pyautogui
            return pyautogui.screenshot()
        except Exception as e:
            if image_grab_error is not None:
                raise RuntimeError(f'Pillow ImageGrab failed: {image_grab_error}; pyautogui failed: {e}')
            raise RuntimeError(f'Screen capture failed: {e}')

    def _capture_origin(self, image):
        if self._os_alias != 'win':
            return 0, 0
        try:
            import ctypes
            user32 = ctypes.windll.user32
            origin_x = int(user32.GetSystemMetrics(76))
            origin_y = int(user32.GetSystemMetrics(77))
            virtual_width = int(user32.GetSystemMetrics(78))
            virtual_height = int(user32.GetSystemMetrics(79))
            if virtual_width == int(image.width) and virtual_height == int(image.height):
                return origin_x, origin_y
        except Exception:
            pass
        return 0, 0

