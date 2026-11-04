"""Manage independent TCP/TLS listening endpoints sharing one SessionAcceptor contract."""
import json
import os
import socket
import tempfile
import threading
import uuid

from core.utils.logger import logger
from server.config.config import SERVER_RUNTIME_DIR, WEB_PORT, WEB_WS_PORT
from server.runtime.listener_protocols import get_listener_protocol, list_listener_protocols


class ListenerManager:
    def __init__(self, server, config_path=None):
        self.server = server
        self.config_path = config_path or os.path.join(SERVER_RUNTIME_DIR, 'listeners.json')
        self.cert_dir = os.path.join(SERVER_RUNTIME_DIR, 'listener_tls')
        self._lock = threading.RLock()
        self._running = {}
        self._configs = self._load()
        self._started = False
        self._errors = {}

    def _load(self):
        default = {'id': 'tcp-default', 'name': 'TCP', 'protocol': 'tcp',
                   'host': self.server.address[0], 'port': self.server.address[1], 'enabled': True}
        if not os.path.isfile(self.config_path):
            return [default]
        with open(self.config_path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            raise ValueError('Invalid listeners.json: expected a nonempty list')
        for item in data:
            self._validate(item, [other for other in data if other is not item])
        return data

    def _save(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.listeners-', dir=os.path.dirname(self.config_path))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self._configs, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.config_path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    @staticmethod
    def _host_overlap(left, right):
        return left == right or left in ('', '0.0.0.0') or right in ('', '0.0.0.0')

    def _validate(self, item, existing):
        if not isinstance(item, dict): raise ValueError('Invalid listener')
        get_listener_protocol(item.get('protocol'))
        name = str(item.get('name') or '').strip()
        if not name or len(name) > 60: raise ValueError('Listener name required (max 60 chars)')
        host = str(item.get('host') or '').strip()
        if host not in ('', '0.0.0.0', '127.0.0.1'):
            # Bind to an assigned local interface only; external host belongs in Agent Build.
            try:
                socket.inet_pton(socket.AF_INET, host)
            except OSError:
                raise ValueError('Listener host must be a local IPv4 address')
        try: port = int(item.get('port'))
        except (TypeError, ValueError): raise ValueError('Invalid port')
        if not 1 <= port <= 65535: raise ValueError('Port must be 1–65535')
        if port in (WEB_PORT, WEB_WS_PORT): raise ValueError('Port reserved for Web/WS')
        if not str(item.get('id') or ''): raise ValueError('Listener id required')
        for other in existing:
            if other['id'] == item['id']: raise ValueError('Duplicate listener id')
            if int(other['port']) == port and self._host_overlap(host, other['host']):
                raise ValueError('Listener host/port conflicts with an existing listener')

    def certificate_fingerprint(self, listener_id):
        with self._lock:
            config = self.get(listener_id)
            protocol = get_listener_protocol(config['protocol'])
            return protocol.certificate_fingerprint(listener_id, self.cert_dir)

    def list_protocols(self):
        return list_listener_protocols()

    def build_settings(self, listener_id, server_port, builder):
        """Resolve build-time transport metadata without protocol-specific branches."""
        with self._lock:
            config = self.get(listener_id)
            if int(config['port']) != int(server_port):
                raise ValueError('Server port does not match selected listener')
            protocol = get_listener_protocol(config['protocol'])
            return {'listener_protocol': protocol.name,
                    'tls_fingerprint': protocol.build_fingerprint(listener_id, builder, self.cert_dir)}

    def _make_listener(self, item):
        protocol = get_listener_protocol(item['protocol'])
        return protocol.create_listener(self.server, item, self.cert_dir)

    def _start_unlocked(self, item):
        if item['id'] in self._running: return
        listener = self._make_listener(item)
        listener.start()
        self._running[item['id']] = listener
        self._errors.pop(item['id'], None)

    def start_all(self):
        with self._lock:
            if self._started: return
            self._started = True
            for item in self._configs:
                if item.get('enabled', True):
                    try: self._start_unlocked(item)
                    except Exception as exc:
                        self._errors[item['id']] = str(exc)
                        logger.error('Listener %s failed: %s', item['id'], exc)

    def stop_all(self):
        with self._lock:
            for item in list(self._running.values()): item.stop()
            self._running.clear()
            self._started = False

    def get(self, listener_id):
        with self._lock:
            for item in self._configs:
                if item['id'] == listener_id: return dict(item)
        raise ValueError('Unknown listener')

    def list(self):
        with self._lock:
            counts = {}
            for session in self.server.connections.all():
                key = getattr(session, 'listener_id', '')
                counts[key] = counts.get(key, 0) + 1
            rows = []
            for item in self._configs:
                protocol = get_listener_protocol(item['protocol'])
                metadata = protocol.describe()
                rows.append({**item,
                             'status': 'listening' if item['id'] in self._running else ('error' if item['id'] in self._errors else 'stopped'),
                             'last_error': self._errors.get(item['id'], ''),
                             'connections': counts.get(item['id'], 0),
                             'protocol_label': metadata['label'],
                             'protocol_build_label': metadata['build_label'],
                             'supported_builders': metadata['supported_builders'],
                             'builder_warning': metadata['builder_warning']})
            return rows

    def create(self, payload):
        with self._lock:
            item = {'id': uuid.uuid4().hex[:12],
                    'name': str(payload.get('name') or '').strip(),
                    'protocol': payload.get('protocol'),
                    'host': str(payload.get('host') or '').strip(),
                    'port': payload.get('port'), 'enabled': True}
            self._validate(item, self._configs)
            item['port'] = int(item['port'])
            if self._started: self._start_unlocked(item)
            self._configs.append(item)
            try: self._save()
            except Exception:
                self._configs.remove(item)
                listener = self._running.pop(item['id'], None)
                if listener: listener.stop()
                raise
            return item

    def set_enabled(self, listener_id, enabled):
        with self._lock:
            item = next((row for row in self._configs if row['id'] == listener_id), None)
            if item is None: raise ValueError('Unknown listener')
            enabled = bool(enabled)
            if enabled == bool(item.get('enabled', True)) and (not self._started or enabled == (listener_id in self._running)):
                return dict(item)
            old_enabled = item.get('enabled', True)
            # Starting is synchronous; keep configuration unchanged on bind failure.
            if enabled and self._started:
                self._start_unlocked(item)
            item['enabled'] = enabled
            try: self._save()
            except Exception:
                item['enabled'] = old_enabled
                if enabled and not old_enabled:
                    listener = self._running.pop(listener_id, None)
                    if listener: listener.stop()
                raise
            if not enabled:
                listener = self._running.pop(listener_id, None)
                if listener: listener.stop()
                self._errors.pop(listener_id, None)
            return dict(item)

    def remove(self, listener_id):
        with self._lock:
            if listener_id == 'tcp-default': raise ValueError('Default TCP listener cannot be removed')
            item = self.get(listener_id)
            self._configs.remove(item)
            try: self._save()
            except Exception:
                self._configs.append(item)
                raise
            listener = self._running.pop(listener_id, None)
            if listener: listener.stop()
            self._errors.pop(listener_id, None)
            return {'removed': listener_id}
