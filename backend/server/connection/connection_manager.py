import threading


class ConnectionManager:
    def __init__(self):
        self._connections_by_client_id = {}
        self._anonymous_connections = []
        self._lock = threading.RLock()

    def add(self, conn):

        with self._lock:
            client_id = getattr(getattr(conn, 'session_info', None), 'client_id', '')
            if client_id:
                current = self._connections_by_client_id.get(client_id)
                if current is not None and getattr(current, 'exclusive_registration', False):
                    raise ValueError('Active session does not allow replacement')
                self._connections_by_client_id[client_id] = conn
            else:
                self._anonymous_connections.append(conn)

    def add_if_absent(self, conn):
        """Atomically refuse a new session that would replace an active Client ID."""
        with self._lock:
            client_id = getattr(getattr(conn, 'session_info', None), 'client_id', '')
            if not client_id or client_id in self._connections_by_client_id:
                return False
            self._connections_by_client_id[client_id] = conn
            return True

    def run_if_current(self, conn, callback, *, allow_missing=False):
        """Serialize Client-ID scoped side effects with replacement registration."""
        with self._lock:
            client_id = getattr(getattr(conn, 'session_info', None), 'client_id', '')
            if client_id:
                registered = self._connections_by_client_id.get(client_id)
                current = registered is conn or (allow_missing and registered is None)
            else:
                current = conn in self._anonymous_connections or allow_missing
            if not current:
                return False
            callback()
            return True

    def remove(self, conn):
        with self._lock:
            client_id = getattr(getattr(conn, 'session_info', None), 'client_id', '')
            if client_id:
                current = self._connections_by_client_id.get(client_id)
                if current is conn:
                    self._connections_by_client_id.pop(client_id, None)
                return

            if conn in self._anonymous_connections:
                self._anonymous_connections.remove(conn)

    def all(self):
        """
        返回当前连接列表快照
        """
        with self._lock:
            return list(self._connections_by_client_id.values()) + list(self._anonymous_connections)

    def list(self):
        """
        兼容旧接口，返回当前连接列表快照
        """
        return self.all()

    def get(self, index):
        with self._lock:
            return self.all()[index]

    def get_by_client_id(self, client_id):
        with self._lock:
            conn = self._connections_by_client_id.get(str(client_id))
            if conn is not None:
                return conn
        raise KeyError(f'Connection not found: {client_id}')

    def find(self, target):
        text = str(target or '').strip()
        if not text:
            raise KeyError('Connection target is empty')

        if text.isdigit():
            return self.get(int(text))

        return self.get_by_client_id(text)

    def last(self):
        with self._lock:
            return self.all()[-1]

    def __getitem__(self, index):
        return self.get(index)

    def __len__(self):
        with self._lock:
            return len(self._connections_by_client_id) + len(self._anonymous_connections)

    def __iter__(self):
        return iter(self.all())

    def __contains__(self, item):
        with self._lock:
            return item in self._connections_by_client_id.values() or item in self._anonymous_connections