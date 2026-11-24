"""Database-backed Keychains with standard-library reversible secret masking."""
import base64
import binascii
import hmac
import os
import secrets
import threading
import uuid
from datetime import datetime
from pathlib import Path


class KeychainStore:
    """Persist credentials in rch.db without storing secret plaintext.

    Back up the Server-local keychains.key together with rch.db to restore secrets.
    This lightweight masking is not a substitute for a vetted encryption cipher.
    """

    SHARED_MACHINE_ID = '__shared__'
    SHARED_HOSTNAME = 'Shared'
    TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
    KIND_LOGIN = 'login'
    KIND_SECRET = 'secret'
    MAX_TEXT_CHARS = 4096
    MAX_SECRET_CHARS = 256 * 1024

    def __init__(self, database, *, key_file_path=None):
        self.database = database
        self._lock = threading.RLock()
        self._key_path = Path(key_file_path) if key_file_path is not None else Path(self.database.db_path).with_name('keychains.key')
        self._key = None
        has_data = self.database.fetch_one('SELECT 1 FROM keychain_entries LIMIT 1') is not None
        if has_data:
            # Never silently generate a replacement key for an existing encrypted DB.
            self._get_key(allow_create=False)

    # Fresh nonce and authentication tag per value; no third-party dependency.
    _NONCE_SIZE = 16
    _TAG_SIZE = 32

    def _get_key(self, *, allow_create=True):
        if self._key is not None:
            return self._key
        if not self._key_path.is_file():
            if not allow_create:
                raise RuntimeError('Keychains encryption key is missing; restore keychains.key alongside rch.db')
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            key = base64.urlsafe_b64encode(secrets.token_bytes(32))
            try:
                fd = os.open(self._key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(key)
                    stream.flush()
                    os.fsync(stream.fileno())
        try:
            encoded = self._key_path.read_bytes().strip()
            key = base64.b64decode(encoded, altchars=b'-_', validate=True)
            if len(key) != 32:
                raise ValueError('expected a 32-byte key')
            self._key = key
        except (OSError, ValueError, binascii.Error) as exc:
            raise RuntimeError('Keychains encryption key is unreadable or invalid') from exc
        return self._key

    @staticmethod
    def _mask(data: bytes, key: bytes, nonce: bytes) -> bytes:
        # HMAC counter stream with a random nonce per value; symmetric to undo.
        stream_key = hmac.digest(key, b'keychain-enc', 'sha256')
        output = bytearray(len(data))
        for offset in range(0, len(data), 32):
            block = hmac.digest(stream_key, nonce + (offset // 32).to_bytes(4, 'big'), 'sha256')
            chunk = data[offset:offset + 32]
            for index, byte in enumerate(chunk):
                output[offset + index] = byte ^ block[index]
        return bytes(output)

    def _encrypt(self, value: str) -> str:
        key = self._get_key()
        nonce = secrets.token_bytes(self._NONCE_SIZE)
        encrypted = self._mask(value.encode('utf-8'), key, nonce)
        mac_key = hmac.digest(key, b'keychain-mac', 'sha256')
        tag = hmac.digest(mac_key, nonce + encrypted, 'sha256')
        return base64.urlsafe_b64encode(nonce + tag + encrypted).decode('ascii')

    def _decrypt(self, token: str) -> str:
        try:
            key = self._get_key(allow_create=False)
            raw = base64.b64decode(token, altchars=b'-_', validate=True)
            if len(raw) < self._NONCE_SIZE + self._TAG_SIZE:
                raise ValueError('token too short')
            nonce = raw[:self._NONCE_SIZE]
            tag = raw[self._NONCE_SIZE:self._NONCE_SIZE + self._TAG_SIZE]
            encrypted = raw[self._NONCE_SIZE + self._TAG_SIZE:]
            mac_key = hmac.digest(key, b'keychain-mac', 'sha256')
            if not hmac.compare_digest(tag, hmac.digest(mac_key, nonce + encrypted, 'sha256')):
                raise ValueError('token authentication failed')
            return self._mask(encrypted, key, nonce).decode('utf-8')
        except (UnicodeError, ValueError, binascii.Error) as exc:
            raise RuntimeError('Keychains secret cannot be decrypted; restore the matching keychains.key') from exc

    def _now_text(self) -> str:
        return datetime.now().strftime(self.TIME_FORMAT)

    def _safe_text(self, value, max_chars: int = MAX_TEXT_CHARS) -> str:
        text = '' if value is None else str(value)
        text = text.strip()
        if max_chars > 0 and len(text) > max_chars:
            return text[:max_chars]
        return text

    def _normalize_machine_id(self, machine_id: str) -> str:
        value = self._safe_text(machine_id)
        return value or self.SHARED_MACHINE_ID

    def _normalize_hostname(self, machine_id: str, hostname: str) -> str:
        normalized_machine_id = self._normalize_machine_id(machine_id)
        if normalized_machine_id == self.SHARED_MACHINE_ID:
            return self.SHARED_HOSTNAME
        return self._safe_text(hostname) or 'Unknown'

    def _normalize_kind(self, value: str) -> str:
        kind = self._safe_text(value).lower()
        if kind not in {self.KIND_LOGIN, self.KIND_SECRET}:
            return self.KIND_LOGIN
        return kind

    def _extract_secret_value(self, item: dict, kind: str) -> str:
        if kind == self.KIND_LOGIN:
            value = item.get('secret_value')
            if value is None:
                value = item.get('password')
            return self._safe_text(value, self.MAX_SECRET_CHARS)

        value = item.get('secret_value')
        if value is None:
            value = item.get('value')
        return self._safe_text(value, self.MAX_SECRET_CHARS)

    def _normalize_entry(self, item, default_machine_id: str = '') -> dict | None:
        if not isinstance(item, dict):
            return None

        now_text = self._now_text()
        machine_id = self._normalize_machine_id(item.get('machine_id') or default_machine_id)
        kind = self._normalize_kind(item.get('kind'))
        name = self._safe_text(item.get('name') or item.get('cred_name'))
        if not name:
            return None

        created_at = self._safe_text(item.get('created_at')) or now_text
        updated_at = self._safe_text(item.get('updated_at')) or created_at or now_text
        secret_value = self._extract_secret_value(item, kind)

        if kind == self.KIND_LOGIN:
            username = self._safe_text(item.get('username'))
            if not username:
                return None
            return {
                'cred_id': self._safe_text(item.get('cred_id')) or uuid.uuid4().hex,
                'machine_id': machine_id,
                'hostname': self._normalize_hostname(machine_id, item.get('hostname')),
                'kind': kind,
                'name': name,
                'username': username,
                'secret_value': secret_value,
                'site': self._safe_text(item.get('site')),
                'note': self._safe_text(item.get('note')),
                'created_at': created_at,
                'updated_at': updated_at,
            }

        return {
            'cred_id': self._safe_text(item.get('cred_id')) or uuid.uuid4().hex,
            'machine_id': machine_id,
            'hostname': self._normalize_hostname(machine_id, item.get('hostname')),
            'kind': kind,
            'name': name,
            'secret_value': secret_value,
            'note': self._safe_text(item.get('note')),
            'created_at': created_at,
            'updated_at': updated_at,
        }


    @staticmethod
    def _row_to_fields(row) -> dict:
        item = dict(row)
        if item['kind'] == 'secret':
            item.pop('username', None)
            item.pop('site', None)
        return item

    def _item_from_row(self, row, *, reveal=True) -> dict:
        item = self._row_to_fields(row)
        ciphertext = item.pop('secret_ciphertext')
        if reveal:
            item['secret_value'] = self._decrypt(ciphertext)
        else:
            item['has_secret'] = bool(ciphertext)
            item['secret_placeholder'] = '••••••••'
        return item

    @staticmethod
    def _to_public_item(item: dict) -> dict:
        result = dict(item)
        secret_value = result.pop('secret_value', '')
        ciphertext = result.pop('secret_ciphertext', '')
        result['has_secret'] = bool(secret_value or ciphertext or result.get('has_secret'))
        result['secret_placeholder'] = '••••••••'
        return result

    def public_item(self, item: dict) -> dict:
        return self._to_public_item(item)

    @staticmethod
    def _entry_values(item: dict, ciphertext: str) -> tuple:
        return (
            item['cred_id'], item['machine_id'], item['hostname'], item['kind'], item['name'],
            item.get('username', ''), ciphertext, item.get('site', ''), item.get('note', ''),
            item['created_at'], item['updated_at'],
        )

    def _ensure_unique_name(self, conn, machine_id: str, name: str, skip_cred_id: str = ''):
        normalized_name = self._safe_text(name).lower()
        for row in conn.execute('SELECT cred_id, name FROM keychain_entries WHERE machine_id = ?', (machine_id,)):
            if skip_cred_id and row['cred_id'] == skip_cred_id:
                continue
            if self._safe_text(row['name']).lower() == normalized_name:
                raise ValueError(f'Credential already exists: {name}')

    def list_items(self, machine_id: str = '', reveal: bool = False) -> list[dict]:
        machine_id_text = self._safe_text(machine_id)
        with self._lock:
            if machine_id_text:
                rows = self.database.connection().execute(
                    'SELECT * FROM keychain_entries WHERE machine_id = ?', (machine_id_text,)
                ).fetchall()
            else:
                rows = self.database.connection().execute('SELECT * FROM keychain_entries').fetchall()
            items = [self._item_from_row(row, reveal=reveal) for row in rows]
        return sorted(
            items,
            key=lambda item: (item.get('updated_at') or item.get('created_at') or '', item.get('name') or ''),
            reverse=True,
        )

    def list_stored_machines(self) -> list[dict]:
        with self._lock:
            rows = self.database.connection().execute(
                'SELECT machine_id, hostname FROM keychain_entries ORDER BY updated_at'
            ).fetchall()
        machines = {}
        for row in rows:
            mid = self._normalize_machine_id(row['machine_id'])
            machines[mid] = {'machine_id': mid, 'hostname': self._normalize_hostname(mid, row['hostname'])}
        return sorted(machines.values(), key=lambda item: (
            item['machine_id'] != self.SHARED_MACHINE_ID, item.get('hostname') or ''))

    def get_item_by_name(self, machine_id: str, name: str, kind: str = '', reveal: bool = True) -> dict:
        mid = self._normalize_machine_id(machine_id)
        wanted_name = self._safe_text(name).lower()
        wanted_kind = self._safe_text(kind).lower()
        if not wanted_name:
            raise ValueError('credential name is required')
        if wanted_kind and wanted_kind not in {self.KIND_LOGIN, self.KIND_SECRET}:
            raise ValueError('kind must be login or secret')
        with self._lock:
            rows = self.database.connection().execute(
                'SELECT * FROM keychain_entries WHERE machine_id = ?', (mid,)
            ).fetchall()
            for row in rows:
                if self._safe_text(row['name']).lower() != wanted_name:
                    continue
                if wanted_kind and row['kind'] != wanted_kind:
                    continue
                return self._item_from_row(row, reveal=reveal)
        raise FileNotFoundError(f'Credential not found: {name}')

    def get_item(self, cred_id: str, reveal: bool = True) -> dict:
        with self._lock:
            row = self.database.connection().execute(
                'SELECT * FROM keychain_entries WHERE cred_id = ?', (self._safe_text(cred_id),)
            ).fetchone()
            if row is not None:
                return self._item_from_row(row, reveal=reveal)
        raise FileNotFoundError('Credential not found')

    def create_item(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('payload is required')
        now = self._now_text()
        item = dict(payload)
        item.update(cred_id=uuid.uuid4().hex, created_at=now, updated_at=now)
        normalized = self._normalize_entry(item)
        if normalized is None:
            raise ValueError('Invalid credential payload')
        if not normalized.get('secret_value'):
            raise ValueError('secret value is required')
        with self._lock, self.database.transaction() as conn:
            self._ensure_unique_name(conn, normalized['machine_id'], normalized['name'])
            ciphertext = self._encrypt(normalized['secret_value'])
            conn.execute('''INSERT INTO keychain_entries (
                cred_id, machine_id, hostname, kind, name, username, secret_ciphertext,
                site, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', self._entry_values(normalized, ciphertext))
        return dict(normalized)

    def update_item(self, cred_id: str, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('payload is required')
        cid = self._safe_text(cred_id)
        with self._lock, self.database.transaction() as conn:
            row = conn.execute('SELECT * FROM keychain_entries WHERE cred_id = ?', (cid,)).fetchone()
            if row is None:
                raise FileNotFoundError('Credential not found')
            original = self._item_from_row(row)
            merged = dict(original)
            merged.update(payload)
            merged['cred_id'] = original['cred_id']
            merged['created_at'] = original['created_at']
            merged['updated_at'] = self._now_text()
            if not any(key in payload for key in ('secret_value', 'password', 'value')):
                merged['secret_value'] = original['secret_value']
            normalized = self._normalize_entry(merged, default_machine_id=original['machine_id'])
            if normalized is None:
                raise ValueError('Invalid credential payload')
            if not normalized.get('secret_value'):
                raise ValueError('secret value is required')
            self._ensure_unique_name(conn, normalized['machine_id'], normalized['name'], skip_cred_id=cid)
            ciphertext = self._encrypt(normalized['secret_value'])
            conn.execute('''UPDATE keychain_entries SET
                machine_id=?, hostname=?, kind=?, name=?, username=?, secret_ciphertext=?,
                site=?, note=?, created_at=?, updated_at=? WHERE cred_id=?''',
                self._entry_values(normalized, ciphertext)[1:] + (cid,))
        return dict(normalized)

    def delete_item(self, cred_id: str) -> dict:
        cid = self._safe_text(cred_id)
        with self._lock, self.database.transaction() as conn:
            row = conn.execute('SELECT * FROM keychain_entries WHERE cred_id = ?', (cid,)).fetchone()
            if row is None:
                raise FileNotFoundError('Credential not found')
            item = self._item_from_row(row)
            conn.execute('DELETE FROM keychain_entries WHERE cred_id = ?', (cid,))
        return item
