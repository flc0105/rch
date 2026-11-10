"""SQLite index for Server artifacts; logical folders never move underlying files."""

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime


SAVED_FOLDERS = (
    ('screenshots', 'Screenshots'),
    ('webcam', 'Webcam'),
    ('downloads', 'Downloads'),
    ('clipboard', 'Clipboard'),
    ('script_output', 'Script Output'),
    ('job_output', 'Job Output'),
    ('command_output', 'Command Output'),
    ('terminal_logs', 'Terminal Logs'),
    ('inbox', 'Inbox'),
)


def classify_artifact(artifact_type, category='', extra=None):
    """Translate producer origin into independent scope, source and default folder."""
    if artifact_type == 'shared_files':
        return 'shared', 'shared_upload', None
    if artifact_type == 'previews':
        return 'preview', 'preview_cache', None
    category = str(category or '').lower().strip()
    source = str((extra or {}).get('source') or '').lower().strip()
    if category in ('screenshot', 'screenshots'):
        kind = 'screenshots'
    elif category in ('webcam', 'camera'):
        kind = 'webcam'
    elif category in ('clipboard', 'clipboard_image', 'clipboard_file'):
        kind = 'clipboard'
    elif category in ('script', 'script_output'):
        kind = 'script_output'
    elif category == 'job_output':
        kind = 'job_output'
    elif source == 'pty_toolbar_action' or category in ('pty_output', 'terminal_logs', 'terminal_output'):
        kind = 'terminal_logs'
    elif source == 'terminal_toolbar_action':
        kind = 'terminal_logs'
    elif artifact_type == 'command_output' or category == 'command_output':
        kind = 'command_output'
    elif category in ('download', 'downloads', 'browser_download', 'bundle'):
        kind = 'downloads'
    else:
        kind = 'inbox'
    return 'saved', kind, f'saved:{kind}'


class ArtifactSqliteCatalog:
    """The only runtime metadata source: files remain on disk, paths are independent of folders."""

    def __init__(self, db_path):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS artifact_folders (
                    folder_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL CHECK(scope IN ('saved', 'shared')),
                    parent_id TEXT REFERENCES artifact_folders(folder_id),
                    name TEXT NOT NULL COLLATE NOCASE,
                    preset INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifact_folders_scope ON artifact_folders(scope, parent_id);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_folders_siblings
                    ON artifact_folders(scope, IFNULL(parent_id, ''), name COLLATE NOCASE);
                CREATE TABLE IF NOT EXISTS artifact_entries (
                    artifact_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL CHECK(scope IN ('saved', 'shared', 'preview')),
                    folder_id TEXT REFERENCES artifact_folders(folder_id),
                    source_kind TEXT NOT NULL,
                    machine_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    saved_path TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifact_entries_scope_time
                    ON artifact_entries(scope, created_at DESC, artifact_id DESC);
                CREATE INDEX IF NOT EXISTS idx_artifact_entries_folder ON artifact_entries(folder_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_artifact_entries_machine ON artifact_entries(machine_id, created_at DESC);
            ''')
            for key, name in SAVED_FOLDERS:
                conn.execute('''INSERT OR IGNORE INTO artifact_folders
                    (folder_id, scope, parent_id, name, preset, created_at)
                    VALUES (?, 'saved', NULL, ?, 1, ?)''',
                    (f'saved:{key}', name, datetime.now().isoformat(timespec='seconds')))

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA busy_timeout=15000')
            conn.execute('PRAGMA journal_mode=WAL')
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _public_payload(payload):
        # An older SQLite record may still contain the pre-folder origin hint.
        # The canonical metadata exposes the normalized source_kind instead.
        payload.pop('category', None)
        payload.pop('_meta_path', None)
        return payload

    def get(self, artifact_id):
        with self._connect() as conn:
            row = conn.execute('SELECT payload_json FROM artifact_entries WHERE artifact_id=?', (artifact_id,)).fetchone()
        return self._public_payload(json.loads(row['payload_json'])) if row else None

    def list(self, *, scope='', folder_id='', machine_id='', source_kind='', search=''):
        where = []
        params = []
        for key, value in (('scope', scope), ('folder_id', folder_id),
                           ('machine_id', machine_id), ('source_kind', source_kind)):
            if value:
                where.append(f'{key}=?')
                params.append(value)
        # A view with no explicit scope excludes ephemeral preview caches.
        if not scope:
            where.append("scope!='preview'")
        if search:
            where.append('payload_json LIKE ?')
            params.append('%' + search + '%')
        condition = ' WHERE ' + ' AND '.join(where) if where else ''
        with self._connect() as conn:
            rows = conn.execute('SELECT payload_json FROM artifact_entries' + condition +
                                ' ORDER BY created_at DESC, artifact_id DESC', params).fetchall()
        return [self._public_payload(json.loads(row['payload_json'])) for row in rows]

    def save(self, payload):
        payload = self._public_payload(dict(payload))
        artifact_id = payload['artifact_id']
        scope = payload['scope']
        folder_id = payload.get('folder_id') or None
        with self._connect() as conn:
            if folder_id:
                folder = conn.execute('SELECT scope FROM artifact_folders WHERE folder_id=?', (folder_id,)).fetchone()
                if not folder or folder['scope'] != scope:
                    raise ValueError('Folder does not belong to this file space')
            conn.execute('''INSERT INTO artifact_entries
                (artifact_id, scope, folder_id, source_kind, machine_id, created_at, saved_path, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    scope=excluded.scope, folder_id=excluded.folder_id,
                    source_kind=excluded.source_kind, machine_id=excluded.machine_id,
                    created_at=excluded.created_at, saved_path=excluded.saved_path,
                    payload_json=excluded.payload_json''',
                (artifact_id, scope, folder_id, payload['source_kind'], payload.get('machine_id', ''),
                 payload['created_at'], payload['saved_path'], json.dumps(payload, ensure_ascii=False)))
        return payload

    def import_records(self, records):
        """Import a prepared set atomically; existing IDs retain their current metadata."""
        imported = 0
        already = 0
        with self._connect() as conn:
            for payload in records:
                payload = self._public_payload(dict(payload))
                artifact_id = payload['artifact_id']
                existing = conn.execute('SELECT saved_path FROM artifact_entries WHERE artifact_id=?',
                                        (artifact_id,)).fetchone()
                if existing:
                    if existing['saved_path'] != payload['saved_path']:
                        raise ValueError(f'Artifact ID conflict: {artifact_id}')
                    already += 1
                    continue
                folder_id = payload.get('folder_id') or None
                if folder_id:
                    folder = conn.execute('SELECT scope FROM artifact_folders WHERE folder_id=?',
                                          (folder_id,)).fetchone()
                    if not folder or folder['scope'] != payload['scope']:
                        raise ValueError(f'Invalid folder for imported artifact: {artifact_id}')
                conn.execute('''INSERT INTO artifact_entries
                    (artifact_id, scope, folder_id, source_kind, machine_id, created_at, saved_path, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (artifact_id, payload['scope'], folder_id, payload['source_kind'],
                     payload.get('machine_id', ''), payload['created_at'], payload['saved_path'],
                     json.dumps(payload, ensure_ascii=False)))
                imported += 1
        return imported, already

    def delete(self, artifact_id):
        with self._connect() as conn:
            conn.execute('DELETE FROM artifact_entries WHERE artifact_id=?', (artifact_id,))

    def list_folders(self, scope=''):
        with self._connect() as conn:
            rows = conn.execute('SELECT * FROM artifact_folders' + (' WHERE scope=?' if scope else '') +
                                ' ORDER BY preset DESC, name COLLATE NOCASE', (scope,) if scope else ()).fetchall()
        return [dict(row) for row in rows]

    def _validate_parent(self, conn, scope, parent_id):
        if not parent_id:
            return
        row = conn.execute('SELECT scope FROM artifact_folders WHERE folder_id=?', (parent_id,)).fetchone()
        if row is None or row['scope'] != scope:
            raise ValueError('Invalid parent folder')

    def create_folder(self, scope, name, parent_id=''):
        if scope not in ('saved', 'shared'):
            raise ValueError('Invalid file space')
        name = str(name or '').strip()
        if not name or name in ('.', '..') or '/' in name or '\\' in name or len(name) > 120:
            raise ValueError('Invalid folder name')
        folder_id = uuid.uuid4().hex
        with self._connect() as conn:
            self._validate_parent(conn, scope, parent_id)
            dup = conn.execute('''SELECT 1 FROM artifact_folders WHERE scope=?
                AND IFNULL(parent_id,'')=? AND name=? COLLATE NOCASE''', (scope, parent_id or '', name)).fetchone()
            if dup:
                raise ValueError('Folder already exists')
            conn.execute('INSERT INTO artifact_folders VALUES(?, ?, ?, ?, 0, ?)',
                         (folder_id, scope, parent_id or None, name, datetime.now().isoformat(timespec='seconds')))
        return self.get_folder(folder_id)

    def get_folder(self, folder_id):
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM artifact_folders WHERE folder_id=?', (folder_id,)).fetchone()
        if not row:
            raise FileNotFoundError('Folder not found')
        return dict(row)

    def rename_folder(self, folder_id, name):
        current = self.get_folder(folder_id)
        if current['preset']:
            raise ValueError('Preset folders cannot be renamed')
        name = str(name or '').strip()
        if not name or '/' in name or '\\' in name or len(name) > 120:
            raise ValueError('Invalid folder name')
        with self._connect() as conn:
            if conn.execute('''SELECT 1 FROM artifact_folders WHERE scope=?
                AND IFNULL(parent_id,'')=? AND name=? COLLATE NOCASE AND folder_id!=?''',
                (current['scope'], current['parent_id'] or '', name, folder_id)).fetchone():
                raise ValueError('Folder already exists')
            conn.execute('UPDATE artifact_folders SET name=? WHERE folder_id=?', (name, folder_id))
        return self.get_folder(folder_id)

    def delete_folder(self, folder_id):
        folder = self.get_folder(folder_id)
        if folder['preset']:
            raise ValueError('Preset folders cannot be deleted')
        with self._connect() as conn:
            if conn.execute('SELECT 1 FROM artifact_entries WHERE folder_id=?', (folder_id,)).fetchone() or \
               conn.execute('SELECT 1 FROM artifact_folders WHERE parent_id=?', (folder_id,)).fetchone():
                raise ValueError('Folder must be empty')
            conn.execute('DELETE FROM artifact_folders WHERE folder_id=?', (folder_id,))
        return {'folder_id': folder_id}

    def move(self, artifact_id, folder_id):
        payload = self.get(artifact_id)
        if payload is None:
            raise FileNotFoundError('Artifact not found')
        if payload['scope'] == 'preview':
            raise ValueError('Preview cache cannot be moved')
        if folder_id:
            folder = self.get_folder(folder_id)
            if folder['scope'] != payload['scope']:
                raise ValueError('Use a dedicated copy action to change sharing scope')
        payload['folder_id'] = folder_id or None
        return self.save(payload)
