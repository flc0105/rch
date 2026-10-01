import threading
from datetime import datetime


from core.utils.json_utils import compact_json_dumps, json_loads_dict
class RecentDeviceStore:
    """
    最近见过的设备缓存。

    规则：
    - 以 machine_id 为维度
    - 同 machine_id 仅保留一条
    - 在线设备写入时覆盖旧记录
    - 下线时更新 offline 状态和时间
    """

    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()
        self._forgotten_machine_keys = set()

    def _normalize_machine_id_key(self, machine_id: str) -> str:
        value = str(machine_id or '').strip()
        return value.lower()

    def _normalize_client_id_key(self, client_id: str) -> str:
        return str(client_id or '').strip()

    def _now_iso(self) -> str:
        return datetime.now().isoformat()

    def _normalize_machine_order(self, value):
        try:
            order = int(value)
        except Exception:
            return None
        return order if order >= 0 else None

    def _read_all_unlocked(self) -> dict:
        rows = self.database.connection().execute(
            'SELECT * FROM recent_devices ORDER BY machine_order ASC, machine_key ASC'
        ).fetchall()
        result = {}
        for row in rows:
            record = json_loads_dict(row['snapshot_json'])
            record.update({
                'recent_device_key': row['machine_key'],
                'machine_id': row['machine_id'],
                'client_id': row['client_id'],
                'machine_order': int(row['machine_order'] or 0),
                'connection_state': row['connection_state'],
                'last_seen_at': row['last_seen_at'],
                'recent_updated_at': row['recent_updated_at'],
                'machine_alias': row['machine_alias'],
                'device_hidden_by_machine': bool(row['device_hidden_by_machine']),
                'hidden_client_ids': json_loads_dict(row['hidden_client_ids_json']),
            })
            result[row['machine_key']] = record
        return result

    def _read_record_unlocked(self, machine_key: str) -> dict | None:
        row = self.database.connection().execute(
            'SELECT * FROM recent_devices WHERE machine_key = ?',
            (machine_key,),
        ).fetchone()
        if row is None:
            return None
        record = json_loads_dict(row['snapshot_json'])
        hidden_client_ids = json_loads_dict(row['hidden_client_ids_json'])
        record.update({
            'recent_device_key': row['machine_key'],
            'machine_id': row['machine_id'],
            'client_id': row['client_id'],
            'machine_order': int(row['machine_order'] or 0),
            'connection_state': row['connection_state'],
            'last_seen_at': row['last_seen_at'],
            'recent_updated_at': row['recent_updated_at'],
            'machine_alias': row['machine_alias'],
            'device_hidden_by_machine': bool(row['device_hidden_by_machine']),
            'hidden_client_ids': self._normalize_bool_map(hidden_client_ids),
        })
        return record

    def _write_record_unlocked(self, machine_key: str, record: dict):
        machine_id = str(record.get('machine_id') or '').strip()
        if not machine_key or not machine_id:
            return
        hidden_client_ids = self._normalize_bool_map(record.get('hidden_client_ids'))
        snapshot = dict(record)
        self.database.connection().execute(
            '''
            INSERT INTO recent_devices(
                machine_key, machine_id, client_id, machine_order, connection_state,
                last_seen_at, recent_updated_at, machine_alias, device_hidden_by_machine,
                hidden_client_ids_json, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(machine_key) DO UPDATE SET
                machine_id = excluded.machine_id,
                client_id = excluded.client_id,
                machine_order = excluded.machine_order,
                connection_state = excluded.connection_state,
                last_seen_at = excluded.last_seen_at,
                recent_updated_at = excluded.recent_updated_at,
                machine_alias = excluded.machine_alias,
                device_hidden_by_machine = excluded.device_hidden_by_machine,
                hidden_client_ids_json = excluded.hidden_client_ids_json,
                snapshot_json = excluded.snapshot_json
            ''',
            (
                machine_key,
                machine_id,
                str(record.get('client_id') or ''),
                int(self._normalize_machine_order(record.get('machine_order')) or 0),
                str(record.get('connection_state') or 'offline'),
                str(record.get('last_seen_at') or ''),
                str(record.get('recent_updated_at') or ''),
                str(record.get('machine_alias') or '').strip(),
                int(bool(record.get('device_hidden_by_machine'))),
                compact_json_dumps(hidden_client_ids),
                compact_json_dumps(snapshot),
            ),
        )

    def _next_machine_order_from_db_unlocked(self) -> int:
        row = self.database.connection().execute(
            'SELECT COALESCE(MAX(machine_order), -1) + 1 FROM recent_devices'
        ).fetchone()
        return int(row[0] if row else 0)

    def _normalize_bool_map(self, value) -> dict:
        if isinstance(value, dict):
            return {
                self._normalize_client_id_key(key): True
                for key, enabled in value.items()
                if self._normalize_client_id_key(key) and bool(enabled)
            }

        if isinstance(value, list):
            return {
                self._normalize_client_id_key(item): True
                for item in value
                if self._normalize_client_id_key(item)
            }

        return {}

    def _find_key_by_client_id_unlocked(self, current: dict, client_id: str) -> str:
        target_client_key = self._normalize_client_id_key(client_id)
        if not target_client_key:
            return ''

        for key, record in current.items():
            if not isinstance(record, dict):
                continue

            if self._normalize_client_id_key(record.get('client_id')) == target_client_key:
                return key

            hidden_client_ids = self._normalize_bool_map(record.get('hidden_client_ids'))
            if target_client_key in hidden_client_ids:
                return key

        return ''

    def _get_record_key_unlocked(self, current: dict, client_id: str = '', machine_id: str = '') -> str:
        machine_key = self._normalize_machine_id_key(machine_id)
        if machine_key:
            return machine_key

        return self._find_key_by_client_id_unlocked(current, client_id)

    def _build_device_view_prefs(self, record: dict, client_id: str = '') -> dict:
        if not isinstance(record, dict):
            return {
                'machine_alias': '',
                'device_alias': '',
                'device_hidden': False,
                'device_hidden_by_client': False,
                'device_hidden_by_machine': False,
                'machine_order': None,
            }

        target_client_key = self._normalize_client_id_key(client_id or record.get('client_id'))
        hidden_client_ids = self._normalize_bool_map(record.get('hidden_client_ids'))
        hidden_by_client = bool(target_client_key and hidden_client_ids.get(target_client_key))
        hidden_by_machine = bool(record.get('device_hidden_by_machine'))
        machine_alias = str(record.get('machine_alias') or '').strip()

        return {
            'machine_alias': machine_alias,
            'device_alias': machine_alias,
            'device_hidden': hidden_by_client or hidden_by_machine,
            'device_hidden_by_client': hidden_by_client,
            'device_hidden_by_machine': hidden_by_machine,
            'machine_order': self._normalize_machine_order(record.get('machine_order')),
        }

    def upsert_from_connection(self, connection_payload: dict):
        if not isinstance(connection_payload, dict):
            return

        machine_id = str(connection_payload.get('machine_id') or '').strip()
        if not machine_id:
            return

        key = self._normalize_machine_id_key(machine_id)
        if not key:
            return

        connection_state = str(connection_payload.get('connection_state') or '').strip().lower()
        disconnected_at = str(connection_payload.get('disconnected_at') or '').strip()
        is_offline_payload = connection_state == 'offline' or bool(disconnected_at)

        with self._lock:
            if key in self._forgotten_machine_keys:
                if is_offline_payload:
                    return
                self._forgotten_machine_keys.discard(key)

            previous = self._read_record_unlocked(key) or {}
            machine_order = self._normalize_machine_order(previous.get('machine_order'))
            if machine_order is None:
                machine_order = self._next_machine_order_from_db_unlocked()

            record = {
                'recent_device_key': key,
                'machine_id': machine_id,
                'machine_order': machine_order,
                # 'machine_id_version': str(connection_payload.get('machine_id_version') or previous.get('machine_id_version') or ''),
                'machine_fingerprint_basis': str(connection_payload.get('machine_fingerprint_basis') or previous.get('machine_fingerprint_basis') or ''),
                'hostname': str(connection_payload.get('hostname') or previous.get('hostname') or ''),
                'client_id': str(connection_payload.get('client_id') or previous.get('client_id') or ''),
                'addr': str(connection_payload.get('addr') or previous.get('addr') or ''),
                'os_type': str(connection_payload.get('os_type') or previous.get('os_type') or ''),
                'os_alias': str(connection_payload.get('os_alias') or previous.get('os_alias') or 'unknown'),
                'os_ver': str(connection_payload.get('os_ver') or previous.get('os_ver') or ''),


                'os_name': str(connection_payload.get('os_name') or previous.get('os_name') or ''),
                'os_full': str(connection_payload.get('os_full') or previous.get('os_full') or ''),
                'arch': str(connection_payload.get('arch') or previous.get('arch') or ''),
                'manufacturer': str(connection_payload.get('manufacturer') or previous.get('manufacturer') or ''),
                'model': str(connection_payload.get('model') or previous.get('model') or ''),

                'integrity': str(connection_payload.get('integrity') or previous.get('integrity') or ''),
                'cwd': str(connection_payload.get('cwd') or previous.get('cwd') or ''),
                'build_version': str(connection_payload.get('build_version') or previous.get('build_version') or ''),
                'client_revision': str(connection_payload.get('client_revision') or previous.get('client_revision') or ''),
                'client_revision_parts': dict(
                    connection_payload.get('client_revision_parts')
                    if isinstance(connection_payload.get('client_revision_parts'), dict)
                    else previous.get('client_revision_parts')
                    if isinstance(previous.get('client_revision_parts'), dict)
                    else {}
                ),
                'python_ver': connection_payload.get('python_ver') or previous.get('python_ver') or '',
                'process_id': connection_payload.get('process_id') or previous.get('process_id') or '',
                'launch_command': connection_payload.get('launch_command') or previous.get('launch_command') or '',
                'username': connection_payload.get('username') or previous.get('username') or '',
                'process_name': connection_payload.get('process_name') or previous.get('process_name') or '',
                'http_transfer_mode': connection_payload.get('http_transfer_mode') or previous.get('http_transfer_mode') or '',
                'python_execution_mode': connection_payload.get('python_execution_mode') or previous.get('python_execution_mode') or '',
                'remote_watchdog_enabled': connection_payload.get('remote_watchdog_enabled'),
                'local_watchdog_enabled': connection_payload.get('local_watchdog_enabled'),
                'connected_at': str(connection_payload.get('connected_at') or previous.get('connected_at') or ''),
                'disconnected_at': str(connection_payload.get('disconnected_at') or ''),
                'last_seen_at': str(connection_payload.get('last_seen_at') or previous.get('last_seen_at') or ''),
                'last_heartbeat_sent_at': str(connection_payload.get('last_heartbeat_sent_at') or previous.get('last_heartbeat_sent_at') or ''),
                'last_heartbeat_ack_at': str(connection_payload.get('last_heartbeat_ack_at') or previous.get('last_heartbeat_ack_at') or ''),
                'last_rtt_ms': connection_payload.get('last_rtt_ms'),
                'stale_after_seconds': connection_payload.get('stale_after_seconds') or previous.get('stale_after_seconds') or 45,
                'connection_state': str(connection_payload.get('connection_state') or previous.get('connection_state') or 'offline'),
                'machine_alias': str(previous.get('machine_alias') or '').strip(),
                'device_hidden_by_machine': bool(previous.get('device_hidden_by_machine')),
                'hidden_client_ids': self._normalize_bool_map(previous.get('hidden_client_ids')),
                'device_view_prefs_updated_at': previous.get('device_view_prefs_updated_at') or '',
                'recent_cached': True,
                'recent_updated_at': self._now_iso(),
            }

            self._write_record_unlocked(key, record)

    def mark_offline(self, machine_id: str, disconnected_at: str = ''):
        key = self._normalize_machine_id_key(machine_id)
        if not key:
            return

        with self._lock:
            if key in self._forgotten_machine_keys:
                return

            record = self._read_record_unlocked(key)
            if not isinstance(record, dict):
                return

            record['recent_device_key'] = key
            record['connection_state'] = 'offline'
            record['disconnected_at'] = str(disconnected_at or self._now_iso())
            record['recent_cached'] = True
            record['recent_updated_at'] = self._now_iso()
            self._write_record_unlocked(key, record)

    def remove_by_identity(self, client_id: str = '', machine_id: str = '') -> dict:
        target_client_id = str(client_id or '').strip()
        target_machine_key = self._normalize_machine_id_key(machine_id)
        removed_keys = []

        with self._lock:
            current = self._read_all_unlocked()

            if target_machine_key and target_machine_key in current:
                removed_keys.append(target_machine_key)

            if target_client_id:
                for key, record in list(current.items()):
                    if not isinstance(record, dict):
                        continue
                    if str(record.get('client_id') or '').strip() == target_client_id:
                        removed_keys.append(key)

            removed_keys = sorted(set(key for key in removed_keys if key))
            forgotten_keys = set(removed_keys)
            if target_machine_key:
                forgotten_keys.add(target_machine_key)

            self._forgotten_machine_keys.update(forgotten_keys)

            if removed_keys:
                placeholders = ','.join('?' for _ in removed_keys)
                self.database.connection().execute(
                    f'DELETE FROM recent_devices WHERE machine_key IN ({placeholders})',
                    tuple(removed_keys),
                )

        return {
            'removed_count': len(removed_keys),
            'removed_keys': removed_keys,
        }

    def get_device_view_prefs(self, client_id: str = '', machine_id: str = '') -> dict:
        target_client_id = self._normalize_client_id_key(client_id)

        with self._lock:
            current = self._read_all_unlocked()
            key = self._get_record_key_unlocked(
                current,
                client_id=target_client_id,
                machine_id=machine_id,
            )
            record = current.get(key) if key else None

        return self._build_device_view_prefs(record, client_id=target_client_id)

    def update_device_view_prefs(self, client_id: str = '', machine_id: str = '', patch: dict = None) -> dict:
        patch = patch or {}
        target_client_id = self._normalize_client_id_key(client_id)
        target_machine_id = str(machine_id or '').strip()
        target_machine_key = self._normalize_machine_id_key(target_machine_id)

        has_machine_alias = 'machine_alias' in patch
        has_client_hidden = 'client_hidden' in patch
        has_machine_hidden = 'machine_hidden' in patch

        if not (has_machine_alias or has_client_hidden or has_machine_hidden):
            return self.get_device_view_prefs(
                client_id=target_client_id,
                machine_id=target_machine_id,
            )

        if has_client_hidden and not target_client_id:
            raise ValueError('Invalid client id')

        if (has_machine_alias or has_machine_hidden) and not target_machine_key:
            raise ValueError('Invalid machine id')

        with self._lock:
            current = self._read_all_unlocked()
            record_key = self._get_record_key_unlocked(
                current,
                client_id=target_client_id,
                machine_id=target_machine_id,
            )

            if not record_key:
                raise ValueError('Invalid device identity')

            record = current.get(record_key)
            if not isinstance(record, dict):
                record = {
                    'recent_device_key': record_key,
                    'machine_id': target_machine_id,
                    'machine_order': self._next_machine_order_from_db_unlocked(),
                    'client_id': target_client_id,
                    'recent_cached': True,
                }

            if target_machine_id:
                record['machine_id'] = target_machine_id
            if target_client_id and not str(record.get('client_id') or '').strip():
                record['client_id'] = target_client_id

            if has_machine_alias:
                machine_alias = str(patch.get('machine_alias') or '').strip()
                if machine_alias:
                    record['machine_alias'] = machine_alias
                else:
                    record.pop('machine_alias', None)

            if has_machine_hidden:
                record['device_hidden_by_machine'] = bool(patch.get('machine_hidden'))

            if has_client_hidden:
                hidden_client_ids = self._normalize_bool_map(record.get('hidden_client_ids'))
                if bool(patch.get('client_hidden')):
                    hidden_client_ids[target_client_id] = True
                else:
                    hidden_client_ids.pop(target_client_id, None)

                if hidden_client_ids:
                    record['hidden_client_ids'] = hidden_client_ids
                else:
                    record.pop('hidden_client_ids', None)

            record['recent_device_key'] = record_key
            record['recent_cached'] = True
            record['device_view_prefs_updated_at'] = self._now_iso()
            self._write_record_unlocked(record_key, record)

            prefs = self._build_device_view_prefs(record, client_id=target_client_id)

        return prefs

    def list_recent_devices(self) -> list[dict]:
        with self._lock:
            current = self._read_all_unlocked()

        items = [value for value in current.values() if isinstance(value, dict)]

        deduped = {}
        for item in items:
            key = str(item.get('recent_device_key') or self._normalize_machine_id_key(item.get('machine_id'))).strip()
            if not key:
                continue

            existing = deduped.get(key)
            if existing is None:
                deduped[key] = item
                continue

            existing_time = str(
                existing.get('last_seen_at')
                or existing.get('connected_at')
                or existing.get('disconnected_at')
                or existing.get('recent_updated_at')
                or ''
            )
            current_time = str(
                item.get('last_seen_at')
                or item.get('connected_at')
                or item.get('disconnected_at')
                or item.get('recent_updated_at')
                or ''
            )
            if current_time >= existing_time:
                deduped[key] = item

        results = list(deduped.values())
        results.sort(
            key=lambda item: str(
                item.get('last_seen_at')
                or item.get('connected_at')
                or item.get('disconnected_at')
                or item.get('recent_updated_at')
                or ''
            ),
            reverse=True,
        )
        return results
