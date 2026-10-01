import secrets
import threading
import time
import uuid
from datetime import datetime

from core.protocol.screen import (
    SCREEN_DEFAULT_CONTROL_ENABLED,
    SCREEN_DEFAULT_FPS,
    SCREEN_MAX_FPS,
    SCREEN_MAX_QUALITY,
    SCREEN_MIN_FPS,
    SCREEN_MIN_QUALITY,
    normalize_screen_fps,
    normalize_screen_quality,
)
from core.protocol.message_types import (
    MSG_TYPE_SCREEN_CLOSE,
    MSG_TYPE_SCREEN_CONFIG,
    MSG_TYPE_SCREEN_INPUT,
    MSG_TYPE_SCREEN_OPEN,
)


class ScreenViewSessionService:
    """
    Server 端屏幕预览与输入控制会话。

    只保留每个会话的最新一帧，避免实时预览产生无意义的帧积压。
    Delta 模式额外保留当前 Keyframe，以便丢弃中间 Delta 后仍能恢复最新画面。
    """

    MIN_FPS = SCREEN_MIN_FPS
    MAX_FPS = SCREEN_MAX_FPS
    MIN_QUALITY = SCREEN_MIN_QUALITY
    MAX_QUALITY = SCREEN_MAX_QUALITY

    def __init__(self, server, event_bus=None):
        self.server = server
        self.event_bus = event_bus
        self._lock = threading.RLock()
        self._sessions = {}

    def create_session(self, client_id: str, fps: int = SCREEN_DEFAULT_FPS, quality: int = 60) -> dict:
        client_id = str(client_id or '').strip()
        session = self.server.get_target_connection_by_client_id(client_id)
        self._cleanup_expired_sessions()
        self._close_existing_client_sessions(client_id)

        screen_session_id = str(uuid.uuid4())
        item = {
            'screen_session_id': screen_session_id,
            'client_id': client_id,
            'status': 'opening',
            'created_at': time.time(),
            'opened_at': 0,
            'closed_at': 0,
            'fps': normalize_screen_fps(fps),
            'quality': normalize_screen_quality(quality),
            'seq': 0,
            'frame_strategy': '',
            'base_frame': None,
            'latest_frame': None,
            'width': 0,
            'height': 0,
            'frame_bytes': 0,
            'captured_at': 0,
            'error': '',
            'control_enabled': SCREEN_DEFAULT_CONTROL_ENABLED,
            'control_error': '',
            'open_notified': False,
            'close_notified': False,
            'ws_token': secrets.token_urlsafe(24),
        }
        with self._lock:
            self._sessions[screen_session_id] = item

        try:
            session.send({
                'type': MSG_TYPE_SCREEN_OPEN,
                'screen_session_id': screen_session_id,
                'fps': item['fps'],
                'quality': item['quality'],
            })
        except Exception as e:
            event_item = None
            with self._lock:
                item['status'] = 'error'
                item['error'] = str(e)
                item['closed_at'] = time.time()
                if not item.get('close_notified'):
                    item['close_notified'] = True
                    event_item = dict(item)
            if event_item:
                self._publish_screen_lifecycle_event(event_item, state='error')
            raise

        return {
            'screen_session_id': screen_session_id,
            'status': item['status'],
            'fps': item['fps'],
            'quality': item['quality'],
            'frame_strategy': item['frame_strategy'],
            'control_enabled': bool(item['control_enabled']),
            'ws_token': item['ws_token'],
        }

    def update_settings(self, screen_session_id: str, fps=None, quality=None) -> dict:
        item = self._get_required(screen_session_id)
        next_fps = normalize_screen_fps(item['fps'] if fps is None else fps)
        next_quality = normalize_screen_quality(item['quality'] if quality is None else quality)

        with self._lock:
            item['fps'] = next_fps
            item['quality'] = next_quality

        session = self.server.get_target_connection_by_client_id(item['client_id'])
        session.send({
            'type': MSG_TYPE_SCREEN_CONFIG,
            'screen_session_id': item['screen_session_id'],
            'fps': next_fps,
            'quality': next_quality,
        })
        return {'ok': True, 'fps': next_fps, 'quality': next_quality}

    def set_control_enabled(self, screen_session_id: str, enabled: bool) -> dict:
        item = self._get_required(screen_session_id)
        next_enabled = bool(enabled)
        with self._lock:
            item['control_enabled'] = next_enabled
            item['control_error'] = ''

        event = {'action': 'prepare' if next_enabled else 'control_off'}
        self._send_input_event(item, event)
        return {'ok': True, 'control_enabled': next_enabled}

    def send_input(self, screen_session_id: str, event: dict) -> dict:
        item = self._get_required(screen_session_id)
        with self._lock:
            if not item.get('control_enabled'):
                return {'ok': False, 'control_enabled': False}

        normalized = self._normalize_input_event(event)
        self._send_input_event(item, normalized)
        return {'ok': True, 'control_enabled': True}

    def close_session(self, screen_session_id: str) -> dict:
        item = self._get_required(screen_session_id)
        try:
            session = self.server.get_target_connection_by_client_id(item['client_id'])
            session.send({
                'type': MSG_TYPE_SCREEN_CLOSE,
                'screen_session_id': item['screen_session_id'],
            })
        except Exception:
            pass

        with self._lock:
            item['control_enabled'] = False
            if item['status'] not in ('closed', 'error'):
                item['status'] = 'closing'
        return {'ok': True}

    def get_updates(self, screen_session_id: str, after_seq: int = 0) -> dict:
        item = self._get_required(screen_session_id)
        with self._lock:
            seq = int(item.get('seq') or 0)
            frames = self._build_frame_updates(item, int(after_seq or 0))
            return {
                'screen_session_id': item['screen_session_id'],
                'status': item.get('status') or '',
                'seq': seq,
                'frames': frames,
                'frame_strategy': item.get('frame_strategy') or '',
                'width': int(item.get('width') or 0),
                'height': int(item.get('height') or 0),
                'frame_bytes': int(item.get('frame_bytes') or 0),
                'captured_at': item.get('captured_at') or 0,
                'fps': int(item.get('fps') or SCREEN_DEFAULT_FPS),
                'quality': int(item.get('quality') or 60),
                'error': item.get('error') or '',
                'control_enabled': bool(item.get('control_enabled')),
                'control_error': item.get('control_error') or '',
            }

    def handle_client_opened(self, screen_session_id: str, fps=None, quality=None, frame_strategy=''):
        event_item = None
        control_item = None
        with self._lock:
            item = self._sessions.get(str(screen_session_id or ''))
            if not item:
                return
            item['status'] = 'open'
            item['opened_at'] = time.time()
            item['frame_strategy'] = self._normalize_frame_strategy(frame_strategy)
            if fps is not None:
                item['fps'] = normalize_screen_fps(fps)
            if quality is not None:
                item['quality'] = normalize_screen_quality(quality)
            if item.get('control_enabled'):
                control_item = dict(item)
            if not item.get('open_notified'):
                item['open_notified'] = True
                event_item = dict(item)

        if control_item:
            self._send_input_event(control_item, {'action': 'prepare'})
        if event_item:
            self._publish_screen_lifecycle_event(event_item, state='started')

    def handle_client_frame(
        self,
        screen_session_id: str,
        data: str,
        width=0,
        height=0,
        frame_bytes=0,
        captured_at=0,
        frame_strategy='',
        frame_type='',
        frame_seq=0,
        base_seq=0,
        patch_x=0,
        patch_y=0,
        patch_width=0,
        patch_height=0,
    ):
        if not data:
            return

        strategy = self._normalize_frame_strategy(frame_strategy)
        if not strategy:
            return
        packet = self._build_frame_packet(
            data=data,
            strategy=strategy,
            frame_type=frame_type,
            frame_seq=frame_seq,
            base_seq=base_seq,
            width=width,
            height=height,
            patch_x=patch_x,
            patch_y=patch_y,
            patch_width=patch_width,
            patch_height=patch_height,
            frame_bytes=frame_bytes,
            captured_at=captured_at,
        )
        if packet is None:
            return

        with self._lock:
            item = self._sessions.get(str(screen_session_id or ''))
            if not item:
                return
            if packet['seq'] <= int(item.get('seq') or 0):
                return

            if strategy == 'keyframe_delta':
                if packet['frame_type'] == 'keyframe':
                    item['base_frame'] = packet
                elif packet['frame_type'] == 'delta':
                    base_frame = item.get('base_frame')
                    if not base_frame or int(base_frame.get('seq') or 0) != packet['base_seq']:
                        return
                else:
                    return
            elif packet['frame_type'] != 'full':
                return

            item['status'] = 'open'
            item['frame_strategy'] = strategy
            item['seq'] = packet['seq']
            item['latest_frame'] = packet
            item['width'] = packet['width']
            item['height'] = packet['height']
            item['frame_bytes'] = packet['frame_bytes']
            item['captured_at'] = packet['captured_at']

    def handle_client_closed(self, screen_session_id: str):
        event_item = None
        with self._lock:
            item = self._sessions.get(str(screen_session_id or ''))
            if not item:
                return
            item['status'] = 'closed'
            item['closed_at'] = time.time()
            item['control_enabled'] = False
            if item.get('open_notified') and not item.get('close_notified'):
                item['close_notified'] = True
                event_item = dict(item)

        if event_item:
            self._publish_screen_lifecycle_event(event_item, state='closed')

    def handle_client_error(self, screen_session_id: str, message: str):
        event_item = None
        with self._lock:
            item = self._sessions.get(str(screen_session_id or ''))
            if not item:
                return
            item['status'] = 'error'
            item['error'] = str(message or 'Screen capture failed')
            item['closed_at'] = time.time()
            item['control_enabled'] = False
            if not item.get('close_notified'):
                item['close_notified'] = True
                event_item = dict(item)

        if event_item:
            self._publish_screen_lifecycle_event(event_item, state='error')

    def handle_client_input_error(self, screen_session_id: str, message: str):
        with self._lock:
            item = self._sessions.get(str(screen_session_id or ''))
            if not item:
                return
            item['control_enabled'] = False
            item['control_error'] = str(message or 'Screen control input failed')

    def handle_client_disconnected(self, client_id: str):
        client_id = str(client_id or '').strip()
        now = time.time()
        event_items = []
        with self._lock:
            for item in self._sessions.values():
                if item.get('client_id') != client_id:
                    continue
                if item.get('status') in ('closed', 'error'):
                    continue
                item['status'] = 'closed'
                item['closed_at'] = now
                item['error'] = 'Client disconnected'
                item['control_enabled'] = False
                if item.get('open_notified') and not item.get('close_notified'):
                    item['close_notified'] = True
                    event_items.append(dict(item))

        for event_item in event_items:
            self._publish_screen_lifecycle_event(event_item, state='closed')

    def authorize_ws(self, screen_session_id: str, token: str) -> bool:
        with self._lock:
            item = self._sessions.get(str(screen_session_id or ''))
            if not item:
                return False
            expected = str(item.get('ws_token') or '')
        return bool(expected) and bool(token) and secrets.compare_digest(expected, str(token))

    def _close_existing_client_sessions(self, client_id: str):
        with self._lock:
            session_ids = [
                item['screen_session_id']
                for item in self._sessions.values()
                if item.get('client_id') == client_id and item.get('status') not in ('closed', 'error')
            ]
        for screen_session_id in session_ids:
            try:
                self.close_session(screen_session_id)
            except Exception:
                pass

    def _send_input_event(self, item: dict, event: dict):
        session = self.server.get_target_connection_by_client_id(item['client_id'])
        session.send({
            'type': MSG_TYPE_SCREEN_INPUT,
            'screen_session_id': item['screen_session_id'],
            'event': event,
        })

    def _normalize_input_event(self, event: dict) -> dict:
        payload = event if isinstance(event, dict) else {}
        action = str(payload.get('action') or '').strip().lower()
        allowed = {
            'mouse_move',
            'mouse_down',
            'mouse_up',
            'mouse_wheel',
            'key_down',
            'key_up',
            'release_all',
        }
        if action not in allowed:
            raise ValueError(f'Unsupported screen input action: {action or "missing"}')

        result = {'action': action}
        if action.startswith('mouse_') and action != 'mouse_wheel':
            result['x'] = self._normalize_pointer(payload.get('x'))
            result['y'] = self._normalize_pointer(payload.get('y'))
        elif action == 'mouse_wheel':
            result['x'] = self._normalize_pointer(payload.get('x'))
            result['y'] = self._normalize_pointer(payload.get('y'))
            try:
                delta = int(payload.get('delta') or 0)
            except Exception:
                delta = 0
            result['delta'] = max(-10, min(10, delta))

        if action in ('mouse_down', 'mouse_up'):
            button = str(payload.get('button') or '').strip().lower()
            if button not in ('left', 'middle', 'right'):
                raise ValueError('Unsupported screen mouse button')
            result['button'] = button

        if action in ('key_down', 'key_up'):
            key = str(payload.get('key') or '').strip()
            if not key or len(key) > 32:
                raise ValueError('Invalid screen keyboard key')
            result['key'] = key
            if action == 'key_down':
                result['repeat'] = bool(payload.get('repeat'))

        return result

    def _normalize_pointer(self, value) -> float:
        try:
            normalized = float(value)
        except Exception as e:
            raise ValueError('Invalid screen pointer coordinate') from e
        return max(0.0, min(1.0, normalized))

    def _publish_screen_lifecycle_event(self, item: dict, state: str):
        if self.event_bus is None:
            return

        try:
            self.event_bus.publish('screen_view_lifecycle', {
                'client_id': item.get('client_id', ''),
                'screen_session_id': item.get('screen_session_id', ''),
                'state': state,
                'status': item.get('status', ''),
                'fps': item.get('fps'),
                'quality': item.get('quality'),
                'frame_strategy': item.get('frame_strategy', ''),
                'error': item.get('error', ''),
                'time': datetime.now().isoformat(),
            })
        except Exception:
            pass

    def _cleanup_expired_sessions(self):
        cutoff = time.time() - 300
        with self._lock:
            expired = [
                screen_session_id
                for screen_session_id, item in self._sessions.items()
                if item.get('status') in ('closed', 'error') and float(item.get('closed_at') or 0) < cutoff
            ]
            for screen_session_id in expired:
                self._sessions.pop(screen_session_id, None)

    def _get_required(self, screen_session_id: str) -> dict:
        with self._lock:
            item = self._sessions.get(str(screen_session_id or ''))
            if item is not None:
                return item
        raise KeyError('Screen view session not found')

    def _build_frame_updates(self, item: dict, after_seq: int) -> list:
        latest_frame = item.get('latest_frame')
        if not latest_frame or int(latest_frame.get('seq') or 0) <= after_seq:
            return []

        if item.get('frame_strategy') != 'keyframe_delta':
            return [dict(latest_frame)]

        base_frame = item.get('base_frame')
        if not base_frame:
            return []

        frames = []
        base_seq = int(base_frame.get('seq') or 0)
        if after_seq < base_seq:
            frames.append(dict(base_frame))

        if int(latest_frame.get('seq') or 0) != base_seq:
            frames.append(dict(latest_frame))

        return frames

    def _build_frame_packet(
        self,
        *,
        data,
        strategy,
        frame_type,
        frame_seq,
        base_seq,
        width,
        height,
        patch_x,
        patch_y,
        patch_width,
        patch_height,
        frame_bytes,
        captured_at,
    ):
        try:
            seq = int(frame_seq)
            base = int(base_seq)
            frame_width = int(width)
            frame_height = int(height)
            next_patch_x = int(patch_x)
            next_patch_y = int(patch_y)
            next_patch_width = int(patch_width)
            next_patch_height = int(patch_height)
        except Exception:
            return None

        normalized_type = str(frame_type or '').strip().lower()
        if seq <= 0 or frame_width <= 0 or frame_height <= 0:
            return None
        if strategy == 'full_jpeg':
            normalized_type = 'full'
            base = seq
            next_patch_x = 0
            next_patch_y = 0
            next_patch_width = frame_width
            next_patch_height = frame_height
        elif normalized_type == 'keyframe':
            base = seq
            next_patch_x = 0
            next_patch_y = 0
            next_patch_width = frame_width
            next_patch_height = frame_height
        elif normalized_type == 'delta':
            if base <= 0 or next_patch_width <= 0 or next_patch_height <= 0:
                return None
            if next_patch_x < 0 or next_patch_y < 0:
                return None
            if next_patch_x + next_patch_width > frame_width:
                return None
            if next_patch_y + next_patch_height > frame_height:
                return None
        else:
            return None

        return {
            'strategy': strategy,
            'frame_type': normalized_type,
            'seq': seq,
            'base_seq': base,
            'frame': str(data),
            'width': frame_width,
            'height': frame_height,
            'patch_x': next_patch_x,
            'patch_y': next_patch_y,
            'patch_width': next_patch_width,
            'patch_height': next_patch_height,
            'frame_bytes': int(frame_bytes or 0),
            'captured_at': captured_at or time.time(),
        }

    def _normalize_frame_strategy(self, value) -> str:
        strategy = str(value or '').strip().lower()
        if strategy in ('full_jpeg', 'keyframe_delta'):
            return strategy
        return ''

