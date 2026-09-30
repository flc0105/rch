import os
import queue
import re
import sys
import time

import psutil

from client.jobs.core.job import Job
from client.runtime.sdk import events


JOB_METADATA = {
    'name': 'wechat_message_event',
    'display_name': 'WeChat Message Event',
    'description': (
        'Listen for Windows shell flash/activation events from WeChat/Weixin, '
        'then use UI Automation only on those events to enrich a Device Event.'
    ),
    'platforms': ['win'],
    'params': [
        {
            'name': 'dedupe_seconds',
            'type': 'number',
            'default': 3.0,
            'min': 0.2,
            'max': 30,
            'description': 'Suppress duplicate shell-flash/message notifications inside this window.',
        },
    ],
}


HSHELL_WINDOWACTIVATED = 4
HSHELL_RUDEAPPACTIVATED = 0x8004
HSHELL_FLASH = 0x8006
WECHAT_PROCESS_NAMES = {'wechat.exe', 'weixin.exe'}

_UNREAD_PATTERNS = (
    re.compile(r'(?P<count>\d+)\s*条新消息', re.IGNORECASE),
    re.compile(r'\[(?P<count>\d+)\s*条?\]', re.IGNORECASE),
    re.compile(r'(?P<count>\d+)\s*new\s+messages?', re.IGNORECASE),
)
_TIMESTAMP_PATTERN = re.compile(
    r'^(?:'
    r'\d{1,2}:\d{2}'
    r'|\d{1,2}/\d{1,2}(?:/\d{2,4})?'
    r'|\d{4}/\d{1,2}/\d{1,2}'
    r'|昨天\s*\d{1,2}:\d{2}'
    r'|Yesterday\s*\d{1,2}:\d{2}'
    r'|星期.'
    r'|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?'
    r')$',
    re.IGNORECASE,
)
_IGNORED_TEXTS = {
    '会话',
    'chats',
    '已置顶',
    '置顶',
    '免打扰',
    '消息免打扰',
}


def _safe_text(value) -> str:
    return '' if value is None else str(value).strip()


def _parse_unread_count(text: str) -> int:
    value = _safe_text(text)
    for pattern in _UNREAD_PATTERNS:
        match = pattern.search(value)
        if match:
            try:
                return max(0, int(match.group('count')))
            except Exception:
                return 0
    return 0


def _strip_unread_suffix(text: str) -> str:
    value = _safe_text(text)
    for pattern in _UNREAD_PATTERNS:
        value = pattern.sub('', value)
    value = value.replace('已置顶', '').strip(' -·|[]()')
    return value.strip()


def _is_wechat_process_name(name: str) -> bool:
    return os.path.basename(_safe_text(name)).lower() in WECHAT_PROCESS_NAMES


def _window_process_info(hwnd: int) -> dict:
    import win32gui
    import win32process

    if not hwnd or not win32gui.IsWindow(hwnd):
        return {}

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process_name = ''
    try:
        process_name = psutil.Process(pid).name()
    except Exception:
        pass

    return {
        'hwnd': int(hwnd),
        'pid': int(pid or 0),
        'process': process_name,
        'title': _safe_text(win32gui.GetWindowText(hwnd)),
        'class_name': _safe_text(win32gui.GetClassName(hwnd)),
    }


def _is_wechat_window(hwnd: int) -> tuple[bool, dict]:
    try:
        info = _window_process_info(hwnd)
    except Exception:
        return False, {}
    return _is_wechat_process_name(info.get('process')), info


def _iter_descendants(root_control, *, max_depth: int = 9, max_nodes: int = 2500):
    pending = [(root_control, 0)]
    visited = 0
    while pending and visited < max_nodes:
        control, depth = pending.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = list(control.GetChildren() or [])
        except Exception:
            continue

        for child in children:
            visited += 1
            yield child
            if visited >= max_nodes:
                return
            pending.append((child, depth + 1))


def _collect_texts(control, *, max_depth: int = 3, max_nodes: int = 120) -> list[str]:
    values = []
    seen = set()

    own_name = _safe_text(getattr(control, 'Name', ''))
    if own_name:
        values.append(own_name)
        seen.add(own_name)

    for child in _iter_descendants(control, max_depth=max_depth, max_nodes=max_nodes):
        value = _safe_text(getattr(child, 'Name', ''))
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _session_from_control(control, index: int) -> dict | None:
    automation_id = _safe_text(getattr(control, 'AutomationId', ''))
    control_type = _safe_text(getattr(control, 'ControlTypeName', ''))
    own_name = _safe_text(getattr(control, 'Name', ''))

    if not automation_id.startswith('session_item_') and control_type != 'ListItemControl':
        return None

    texts = _collect_texts(control)
    combined = ' | '.join(texts)
    unread_count = _parse_unread_count(combined)
    if unread_count <= 0 and automation_id.startswith('session_item_'):
        # Some WeChat 4.x builds expose the unread badge as a child TextControl
        # whose Name is only the number rather than the phrase 'N条新消息'.
        for text in texts[1:]:
            if text.isdigit():
                candidate_count = int(text)
                if 0 < candidate_count <= 999:
                    unread_count = candidate_count
                    break

    sender = ''
    if automation_id.startswith('session_item_'):
        sender = _safe_text(automation_id[len('session_item_'):])
    if not sender:
        sender = _strip_unread_suffix(own_name)

    summary_candidates = []
    for text in texts:
        cleaned = _strip_unread_suffix(text)
        lowered = cleaned.lower()
        if not cleaned:
            continue
        if sender and cleaned == sender:
            continue
        if lowered in _IGNORED_TEXTS:
            continue
        if _TIMESTAMP_PATTERN.match(cleaned):
            continue
        if cleaned.isdigit():
            continue
        if any(pattern.search(text) for pattern in _UNREAD_PATTERNS) and cleaned == sender:
            continue
        summary_candidates.append(cleaned)

    # Session-list controls usually expose sender first and preview text later.
    # Prefer the last useful text, but keep it bounded before sending over SSE.
    summary = summary_candidates[-1] if summary_candidates else ''
    if len(summary) > 500:
        summary = summary[:500]

    key = automation_id or sender or f'index:{index}'
    return {
        'key': key,
        'automation_id': automation_id,
        'sender': sender,
        'summary': summary,
        'unread_count': unread_count,
        'raw_name': own_name,
        'order': index,
    }


def _collect_sessions_from_root(root_control, *, limit: int = 40) -> list[dict]:
    sessions = []
    seen = set()

    for control in _iter_descendants(root_control):
        try:
            session = _session_from_control(control, len(sessions))
        except Exception:
            continue
        if not session:
            continue
        key = session.get('key') or ''
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        sessions.append(session)
        if len(sessions) >= limit:
            break

    return sessions


def _choose_message_candidate(current: list[dict], previous: dict[str, dict]) -> dict | None:
    if not current:
        return None

    changed = []
    unread = []
    for session in current:
        count = int(session.get('unread_count') or 0)
        if count <= 0:
            continue
        unread.append(session)
        old = previous.get(session.get('key') or '') or {}
        old_count = int(old.get('unread_count') or 0)
        old_summary = _safe_text(old.get('summary'))
        summary = _safe_text(session.get('summary'))
        if count > old_count or (summary and summary != old_summary):
            changed.append(session)

    candidates = changed or unread
    if not candidates:
        return None

    # Preserve the order exposed by the session list. The newest/most-relevant
    # session is commonly near the top after a shell flash.
    candidates.sort(key=lambda item: int(item.get('order') or 0))
    return candidates[0]


def _snapshot_map(sessions: list[dict]) -> dict[str, dict]:
    result = {}
    for session in sessions:
        key = _safe_text(session.get('key'))
        if key:
            result[key] = dict(session)
    return result


class WechatMessageEvent(Job):
    def __init__(self):
        super().__init__()
        self._shell_events = queue.Queue()
        self._shell_message = 0
        self._hwnd = 0
        self._class_name = ''
        self._last_sessions = {}
        self._last_emit_signature = None
        self._last_emit_at = 0.0
        self._last_emit_process_key = ''
        self._uia_module = None
        self._uia_import_error = ''

    def run(self):
        if sys.platform != 'win32':
            self._report_state('error', status=0, text='WeChat Message Event is Windows-only')
            self.mark_stopped()
            return

        import ctypes
        import pythoncom
        import win32api
        import win32con
        import win32gui

        self.mark_running()
        failed = False
        hinstance = 0
        dedupe_seconds = float(self.get_job_param('dedupe_seconds', 3.0) or 3.0)
        pythoncom.CoInitialize()

        try:
            hinstance = win32api.GetModuleHandle(None)
            self._class_name = f'RCHWechatMessageEvent_{os.getpid()}_{id(self)}'

            wnd_class = win32gui.WNDCLASS()
            wnd_class.hInstance = hinstance
            wnd_class.lpszClassName = self._class_name
            wnd_class.lpfnWndProc = self._wnd_proc
            win32gui.RegisterClass(wnd_class)

            self._hwnd = win32gui.CreateWindow(
                self._class_name,
                'RCH WeChat Message Event',
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                hinstance,
                None,
            )
            self._shell_message = win32gui.RegisterWindowMessage('SHELLHOOK')
            user32 = ctypes.windll.user32
            try:
                from ctypes import wintypes

                user32.RegisterShellHookWindow.argtypes = [wintypes.HWND]
                user32.RegisterShellHookWindow.restype = wintypes.BOOL
                user32.DeregisterShellHookWindow.argtypes = [wintypes.HWND]
                user32.DeregisterShellHookWindow.restype = wintypes.BOOL
            except Exception:
                pass
            if not user32.RegisterShellHookWindow(self._hwnd):
                raise RuntimeError('RegisterShellHookWindow failed')

            self.send_to_server(1, 'WeChat shell-hook message watcher started', 0)

            while not self.stop_event.is_set():
                if win32gui.PumpWaitingMessages():
                    break
                self._drain_shell_events(dedupe_seconds)
                self.stop_event.wait(0.05)

            # Process anything already queued before shutdown, but do not wait.
            self._drain_shell_events(dedupe_seconds)
        except Exception as exc:
            failed = True
            self.is_running = False
            self.stop_event.set()
            self._report_state('error', status=0, text=str(exc))
            self.send_to_server(0, f'WeChat message watcher failed: {exc}', 1)
        finally:
            try:
                if self._hwnd:
                    ctypes.windll.user32.DeregisterShellHookWindow(self._hwnd)
            except Exception:
                pass
            try:
                if self._hwnd and win32gui.IsWindow(self._hwnd):
                    win32gui.DestroyWindow(self._hwnd)
            except Exception:
                pass
            try:
                if self._class_name:
                    win32gui.UnregisterClass(self._class_name, hinstance)
            except Exception:
                pass
            pythoncom.CoUninitialize()
            self._hwnd = 0
            if not failed:
                self.mark_stopped()

    def stop(self, notify: bool = True):
        self.request_stop(notify=notify)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        import win32con
        import win32gui

        if msg == self._shell_message:
            code = int(wparam)
            target_hwnd = int(lparam or 0)
            if code in (HSHELL_FLASH, HSHELL_WINDOWACTIVATED, HSHELL_RUDEAPPACTIVATED):
                self._shell_events.put((code, target_hwnd, time.monotonic()))
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _drain_shell_events(self, dedupe_seconds: float):
        while True:
            try:
                code, hwnd, observed_at = self._shell_events.get_nowait()
            except queue.Empty:
                return
            try:
                self._handle_shell_event(code, hwnd, observed_at, dedupe_seconds)
            except Exception as exc:
                self.send_to_server(0, f'Shell event handling failed: {exc}', 0)

    def _handle_shell_event(self, code: int, hwnd: int, observed_at: float, dedupe_seconds: float):
        is_wechat, window_info = _is_wechat_window(hwnd)
        if not is_wechat:
            return

        event_name = {
            HSHELL_WINDOWACTIVATED: 'ACTIVATE',
            HSHELL_RUDEAPPACTIVATED: 'RUDE_ACTIVATE',
            HSHELL_FLASH: 'FLASH',
        }.get(code, str(code))
        process_name = _safe_text(window_info.get('process')) or 'WeChat'
        process_key = os.path.basename(process_name).lower() or 'wechat'
        self.send_to_server(
            1,
            f'Shell {event_name}: process={process_name} hwnd={int(hwnd or 0)} '
            f'title={_safe_text(window_info.get("title"))!r}',
            0,
        )

        if code in (HSHELL_WINDOWACTIVATED, HSHELL_RUDEAPPACTIVATED):
            # Activation is useful as a cheap resync point. We only touch UIA on
            # shell events, and activation itself never emits a received-message event.
            sessions, enrichment = self._read_wechat_sessions(hwnd)
            if sessions:
                self._last_sessions = _snapshot_map(sessions)
            self.send_to_server(
                1,
                f'UIA baseline: sessions={len(sessions)} matched={bool(enrichment.get("matched"))} '
                f'window={int(enrichment.get("window_hwnd") or 0)} '
                f'error={_safe_text(enrichment.get("error"))!r}',
                0,
            )
            return

        if code != HSHELL_FLASH:
            return

        sessions, enrichment = self._read_wechat_sessions(hwnd)
        candidate = _choose_message_candidate(sessions, self._last_sessions)
        if sessions:
            self._last_sessions = _snapshot_map(sessions)

        data = {
            'trigger': 'shell_flash',
            'window': window_info,
            'enrichment': enrichment,
        }
        if candidate:
            data['session'] = {
                'sender': candidate.get('sender') or '',
                'summary': candidate.get('summary') or '',
                'unread_count': int(candidate.get('unread_count') or 0),
                'automation_id': candidate.get('automation_id') or '',
            }

        sender = _safe_text((data.get('session') or {}).get('sender'))
        summary = _safe_text((data.get('session') or {}).get('summary'))
        unread_count = int((data.get('session') or {}).get('unread_count') or 0)
        if candidate:
            self.send_to_server(
                1,
                f'UIA FLASH: sessions={len(sessions)} sender={sender!r} unread={unread_count} '
                f'summary={summary[:160]!r}',
                0,
            )
        else:
            self.send_to_server(
                1,
                f'UIA FLASH fallback: sessions={len(sessions)} matched={bool(enrichment.get("matched"))} '
                f'window={int(enrichment.get("window_hwnd") or 0)} '
                f'error={_safe_text(enrichment.get("error"))!r}',
                0,
            )

        # A single WeChat notification can produce more than one HSHELL_FLASH,
        # sometimes through different WeChat-owned HWNDs.  Candidate-backed
        # events keep their semantic signature, while generic fallback uses the
        # process rather than HWND so those sibling flashes collapse together.
        signature = (sender, summary, unread_count) if candidate else ('generic', process_key)
        now = time.monotonic()
        elapsed = now - self._last_emit_at
        same_signature = self._last_emit_signature == signature
        crosses_generic_boundary = (
            self._last_emit_process_key == process_key
            and elapsed < dedupe_seconds
            and (
                not candidate
                or (
                    isinstance(self._last_emit_signature, tuple)
                    and self._last_emit_signature
                    and self._last_emit_signature[0] == 'generic'
                )
            )
        )
        if elapsed < dedupe_seconds and (same_signature or crosses_generic_boundary):
            self.send_to_server(
                1,
                f'Duplicate WeChat FLASH suppressed: process={process_name} '
                f'elapsed={elapsed:.2f}s signature={signature!r}',
                0,
            )
            return

        self._last_emit_signature = signature
        self._last_emit_process_key = process_key
        self._last_emit_at = now

        if sender and summary:
            message = f'WeChat message from {sender}: {summary}'
        elif sender:
            suffix = f' ({unread_count} unread)' if unread_count else ''
            message = f'WeChat message from {sender}{suffix}'
        else:
            message = 'WeChat received a new message'

        try:
            events.emit(
                'app.wechat.message_received',
                data=data,
                message=message,
            )
            self.send_to_server(1, f'Device event emitted: {message}', 0)
        except Exception as exc:
            self.send_to_server(0, f'Device event emit failed: {exc}', 0)

    def _get_uia_module(self):
        if self._uia_module is not None:
            return self._uia_module
        if self._uia_import_error:
            return None
        try:
            import uiautomation as auto

            self._uia_module = auto
            return auto
        except Exception as exc:
            self._uia_import_error = str(exc)
            return None

    def _read_wechat_sessions(self, triggered_hwnd: int) -> tuple[list[dict], dict]:
        auto = self._get_uia_module()
        if auto is None:
            return [], {
                'uia_available': False,
                'matched': False,
                'error': self._uia_import_error or 'uiautomation unavailable',
            }

        handles = self._candidate_wechat_windows(triggered_hwnd)
        last_error = ''
        best_sessions = []
        best_hwnd = 0

        for hwnd in handles:
            try:
                root = auto.ControlFromHandle(hwnd)
                if not root:
                    continue
                sessions = _collect_sessions_from_root(root)
                if len(sessions) > len(best_sessions):
                    best_sessions = sessions
                    best_hwnd = hwnd
                if any(int(item.get('unread_count') or 0) > 0 for item in sessions):
                    best_sessions = sessions
                    best_hwnd = hwnd
                    break
            except Exception as exc:
                last_error = str(exc)

        return best_sessions, {
            'uia_available': True,
            'matched': bool(best_sessions),
            'window_hwnd': int(best_hwnd or 0),
            'session_count': len(best_sessions),
            'error': last_error,
        }

    def _candidate_wechat_windows(self, triggered_hwnd: int) -> list[int]:
        import win32gui

        handles = []
        seen = set()

        def add(hwnd):
            try:
                hwnd = int(hwnd or 0)
            except Exception:
                return
            if not hwnd or hwnd in seen:
                return
            is_wechat, _ = _is_wechat_window(hwnd)
            if not is_wechat:
                return
            seen.add(hwnd)
            handles.append(hwnd)

        add(triggered_hwnd)

        def callback(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                add(hwnd)
            except Exception:
                return

        try:
            win32gui.EnumWindows(callback, None)
        except Exception:
            pass

        return handles
