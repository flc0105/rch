from server.application.keychains.keychain_store import KeychainStore



class WebKeychainApi:
    """
    Web 凭证管理子外观。

    说明：
    - 凭证只保存在服务端 runtime/keychains JSON 中
    - 不向 client 下发任何指令，也不依赖 client 执行
    - 列表默认不返回 secret_value，查看 / 编辑时才读取明文
    """

    def __init__(self, server, keychain_store: KeychainStore, connection_service):
        self.server = server
        self.keychain_store = keychain_store
        self.connection_service = connection_service

    def _safe_text(self, value) -> str:
        return '' if value is None else str(value).strip()

    def _normalize_machine_id(self, machine_id: str) -> str:
        return self._safe_text(machine_id) or KeychainStore.SHARED_MACHINE_ID

    def _normalize_hostname(self, machine_id: str, hostname: str) -> str:
        normalized_machine_id = self._normalize_machine_id(machine_id)
        if normalized_machine_id == KeychainStore.SHARED_MACHINE_ID:
            return KeychainStore.SHARED_HOSTNAME
        return self._safe_text(hostname) or 'Unknown'

    def _connection_machines(self) -> list[dict]:
        machines = {}
        try:
            connections = self.connection_service.get_connections_payload()
        except Exception:
            connections = []

        for item in connections:
            if not isinstance(item, dict):
                continue
            machine_id = self._safe_text(item.get('machine_id'))
            if not machine_id:
                continue
            machines[machine_id] = {
                'machine_id': machine_id,
                'hostname': self._safe_text(item.get('hostname')) or 'Unknown',
                'connection_state': self._safe_text(item.get('connection_state')) or 'offline',
            }
        return list(machines.values())

    def list_machines(self) -> list[dict]:
        machine_map = {
            KeychainStore.SHARED_MACHINE_ID: {
                'machine_id': KeychainStore.SHARED_MACHINE_ID,
                'hostname': KeychainStore.SHARED_HOSTNAME,
                'connection_state': 'shared',
            }
        }

        for item in self._connection_machines():
            machine_id = self._safe_text(item.get('machine_id'))
            if not machine_id:
                continue
            machine_map[machine_id] = item

        for item in self.keychain_store.list_stored_machines():
            machine_id = self._safe_text(item.get('machine_id'))
            if not machine_id:
                continue
            existing = machine_map.get(machine_id, {})
            machine_map[machine_id] = {
                'machine_id': machine_id,
                'hostname': self._safe_text(existing.get('hostname')) or self._safe_text(item.get('hostname')) or 'Unknown',
                'connection_state': self._safe_text(existing.get('connection_state')) or 'offline',
            }

        def _sort_key(item):
            machine_id = self._safe_text(item.get('machine_id'))
            if machine_id == KeychainStore.SHARED_MACHINE_ID:
                return (0, 'shared')
            return (1, self._safe_text(item.get('hostname')).lower(), machine_id.lower())

        return sorted(machine_map.values(), key=_sort_key)

    def _resolve_hostname(self, machine_id: str, requested_hostname: str = '') -> str:
        normalized_machine_id = self._normalize_machine_id(machine_id)
        if requested_hostname:
            return self._normalize_hostname(normalized_machine_id, requested_hostname)

        for item in self.list_machines():
            if self._safe_text(item.get('machine_id')) == normalized_machine_id:
                return self._normalize_hostname(normalized_machine_id, item.get('hostname'))
        return self._normalize_hostname(normalized_machine_id, '')

    def _normalize_payload(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('payload is required')

        normalized = dict(payload)
        machine_id = self._normalize_machine_id(normalized.get('machine_id'))
        normalized['machine_id'] = machine_id
        normalized['hostname'] = self._resolve_hostname(machine_id, normalized.get('hostname') or '')
        return normalized

    def _client_identity(self):
        # The Web API also runs in standalone service tests (no Flask context).
        try:
            from flask import g
            return getattr(g, 'client_session_identity', None)
        except (ImportError, RuntimeError):
            return None

    def _client_machine_id(self) -> str:
        identity = self._client_identity()
        if not identity:
            return ''
        return self._safe_text(identity.get('machine_id'))

    def _check_client_keychain_machine(self, machine_id: str):
        identity = self._client_identity()
        if identity is None:
            return
        client_machine = self._safe_text(identity.get('machine_id'))
        if machine_id != KeychainStore.SHARED_MACHINE_ID and (not client_machine or machine_id != client_machine):
            raise PermissionError('Client may access only its machine or Server Shared Keychains')

    def _visible_machines(self):
        machines = self.list_machines()
        client_machine = self._client_machine_id()
        if not client_machine:
            return machines
        return [item for item in machines
                if item.get('machine_id') in (client_machine, KeychainStore.SHARED_MACHINE_ID)]

    def list_keychains(self, machine_id: str = '') -> dict:
        normalized_machine_id = self._safe_text(machine_id) or self._client_machine_id()
        if self._client_identity() is not None and not normalized_machine_id:
            raise PermissionError('Client machine identity is required')
        self._check_client_keychain_machine(normalized_machine_id)
        return {
            'items': self.keychain_store.list_items(normalized_machine_id, reveal=False),
            'machines': self._visible_machines(),
            'shared_machine_id': KeychainStore.SHARED_MACHINE_ID,
            'shared_hostname': KeychainStore.SHARED_HOSTNAME,
        }

    def get_keychain_item(self, cred_id: str) -> dict:
        item = self.keychain_store.get_item(cred_id, reveal=True)
        if item:
            self._check_client_keychain_machine(item.get('machine_id') or '')
        return {
            'item': item,
            'machines': self._visible_machines(),
        }

    def resolve_keychain_item(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('payload is required')

        name = self._safe_text(payload.get('name'))
        kind = self._safe_text(payload.get('kind')).lower()
        scope = self._safe_text(payload.get('scope')).lower()
        machine_id = self._safe_text(payload.get('machine_id'))

        if not name:
            raise ValueError('name is required')
        if kind and kind not in {KeychainStore.KIND_LOGIN, KeychainStore.KIND_SECRET}:
            raise ValueError('kind must be login or secret')

        if scope in ('shared', KeychainStore.SHARED_MACHINE_ID):
            machine_id = KeychainStore.SHARED_MACHINE_ID
        elif not scope or scope == 'machine':
            machine_id = self._normalize_machine_id(machine_id)
        else:
            raise ValueError('scope must be machine or shared')

        self._check_client_keychain_machine(machine_id)
        item = self.keychain_store.get_item_by_name(machine_id, name, kind=kind, reveal=True)
        return {
            'item': item,
            'shared_machine_id': KeychainStore.SHARED_MACHINE_ID,
            'shared_hostname': KeychainStore.SHARED_HOSTNAME,
        }

    def create_keychain_item(self, payload: dict) -> dict:
        normalized = self._normalize_payload(payload)
        self._check_client_keychain_machine(normalized['machine_id'])
        item = self.keychain_store.create_item(normalized)
        return {
            'item': self.keychain_store.public_item(item),
            'items': self.keychain_store.list_items(item.get('machine_id') or '', reveal=False),
            'machines': self._visible_machines(),
            'message': f'Saved credential: {item.get("name", "")}',
        }

    def update_keychain_item(self, cred_id: str, payload: dict) -> dict:
        existing = self.keychain_store.get_item(cred_id, reveal=False)
        if existing:
            self._check_client_keychain_machine(existing.get('machine_id') or '')
        data = dict(payload or {})
        if existing and not data.get('machine_id'):
            data['machine_id'] = existing.get('machine_id')
        normalized = self._normalize_payload(data)
        self._check_client_keychain_machine(normalized['machine_id'])
        item = self.keychain_store.update_item(cred_id, normalized)
        return {
            'item': self.keychain_store.public_item(item),
            'items': self.keychain_store.list_items(item.get('machine_id') or '', reveal=False),
            'machines': self._visible_machines(),
            'message': f'Updated credential: {item.get("name", "")}',
        }

    def delete_keychain_item(self, cred_id: str) -> dict:
        existing = self.keychain_store.get_item(cred_id, reveal=False)
        if existing:
            self._check_client_keychain_machine(existing.get('machine_id') or '')
        item = self.keychain_store.delete_item(cred_id)
        return {
            'item': self.keychain_store.public_item(item),
            'items': self.keychain_store.list_items(item.get('machine_id') or '', reveal=False),
            'machines': self._visible_machines(),
            'message': f'Deleted credential: {item.get("name", "")}',
        }
