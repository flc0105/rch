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
    ('script_output', 'Script Files'),
    ('job_output', 'Job Files'),
    ('command_output', 'Command Output'),
    ('terminal_logs', 'Terminal Logs'),
    ('inbox', 'Inbox'),
)

SAVED_FOLDER_IDS = frozenset(f'saved:{key}' for key, _ in SAVED_FOLDERS)
# Preserve stable folder IDs from the SQLite catalog while making the origin
# categories unambiguous: these contain produced files, not stdout snapshots.
SOURCE_FOLDER_IDS = {
    'script_file': 'saved:script_output',
    'job_file': 'saved:job_output',
}


def classify_artifact(artifact_type, category='', extra=None):
    """Translate producer origin into independent scope, source and default folder."""
    if artifact_type == 'shared_files':
        return 'shared', 'shared_upload', None
    if artifact_type == 'previews':
        return 'preview', 'preview_cache', None
    category = str(category or '').lower().strip()
    source = str((extra or {}).get('source') or '').lower().strip()
    # Command output is a saved execution result, regardless of whether the
    # originating command was a script, a background job, or a shell command.
    if source in ('pty_toolbar_action', 'terminal_toolbar_action') or category in ('pty_output', 'terminal_logs', 'terminal_output'):
        kind = 'terminal_logs'
    elif artifact_type == 'command_output' or category == 'command_output':
        kind = 'command_output'
    elif category in ('screenshot', 'screenshots', 'app_screenshot', 'scheduled_screenshot'):
        kind = 'screenshots'
    elif category in ('webcam', 'camera'):
        kind = 'webcam'
    elif category in ('clipboard', 'clipboard_image', 'clipboard_file'):
        kind = 'clipboard'
    elif category in ('script', 'script_output', 'script_file'):
        kind = 'script_file'
    elif category in ('job_output', 'job_file'):
        kind = 'job_file'
    elif category in ('download', 'downloads', 'browser_download', 'bundle'):
        kind = 'downloads'
    else:
        kind = 'inbox'
    return 'saved', kind, SOURCE_FOLDER_IDS.get(kind, f'saved:{kind}')


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
            self._normalize_saved_folders(conn)
            self._upgrade_saved_folder_names(conn)
            self._normalize_existing_output_records(conn)

    @staticmethod
    def _upgrade_saved_folder_names(conn):
        # Rename the v12 preset folders in place, retaining their stable IDs
        # and every existing Artifact relationship. Labels no longer conflate
        # generated files with saved command output.
        for folder_id, new_name in (
            ('saved:script_output', 'Script Files'),
            ('saved:job_output', 'Job Files'),
        ):
            conn.execute('UPDATE artifact_folders SET name=? WHERE folder_id=? AND scope=?',
                         (new_name, folder_id, 'saved'))

    @staticmethod
    def _normalize_existing_output_records(conn):
        """Align v12 execution snapshots and generated files with the new folder meanings."""
        rows = conn.execute("""SELECT artifact_id, folder_id, source_kind, payload_json FROM artifact_entries
            WHERE scope='saved' AND source_kind IN ('script_output', 'job_output')""").fetchall()
        for row in rows:
            payload = json.loads(row['payload_json'])
            old_kind = row['source_kind']
            old_folder = row['folder_id']
            if payload.get('artifact_type') == 'command_output':
                extra = payload.get('extra') or {}
                source = str(extra.get('source') or '').strip()
                target_kind = ('terminal_logs' if source in ('pty_toolbar_action', 'terminal_toolbar_action')
                               else 'command_output')
                old_auto_folder = old_folder in ('saved:script_output', 'saved:job_output', 'saved:command_output')
                new_folder = ('saved:terminal_logs' if target_kind == 'terminal_logs' else 'saved:command_output') if old_auto_folder else old_folder
            elif old_kind in ('script_output', 'job_output'):
                target_kind = 'script_file' if old_kind == 'script_output' else 'job_file'
                new_folder = old_folder
            else:
                continue
            if target_kind == old_kind and new_folder == old_folder:
                continue
            payload['source_kind'] = target_kind
            payload['folder_id'] = new_folder
            conn.execute('UPDATE artifact_entries SET source_kind=?, folder_id=?, payload_json=? WHERE artifact_id=?',
                         (target_kind, new_folder, json.dumps(payload, ensure_ascii=False), row['artifact_id']))

    @staticmethod
    def _saved_folder_id(source_kind):
        kind = str(source_kind or '').strip()
        target = f'saved:{kind}'
        return SOURCE_FOLDER_IDS.get(kind, target if target in SAVED_FOLDER_IDS else 'saved:inbox')

    def _normalize_saved_folders(self, conn):
        """Retire earlier user-defined Saved folders without deleting any file bytes."""
        custom = conn.execute("SELECT 1 FROM artifact_folders WHERE scope='saved' AND preset=0 LIMIT 1").fetchone()
        misplaced = conn.execute("""SELECT 1 FROM artifact_entries
            WHERE scope='saved' AND (folder_id IS NULL OR folder_id NOT IN
                (SELECT folder_id FROM artifact_folders WHERE scope='saved' AND preset=1)) LIMIT 1""").fetchone()
        if not custom and not misplaced:
            return
        rows = conn.execute("""SELECT artifact_id, source_kind, payload_json FROM artifact_entries
            WHERE scope='saved' AND (folder_id IS NULL OR folder_id NOT IN
                (SELECT folder_id FROM artifact_folders WHERE scope='saved' AND preset=1))""").fetchall()
        for row in rows:
            payload = json.loads(row['payload_json'])
            target = self._saved_folder_id(row['source_kind'])
            payload['folder_id'] = target
            conn.execute('UPDATE artifact_entries SET folder_id=?, payload_json=? WHERE artifact_id=?',
                         (target, json.dumps(payload, ensure_ascii=False), row['artifact_id']))
        conn.execute("DELETE FROM artifact_folders WHERE scope='saved' AND preset=0")

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
        if scope == 'saved':
            folder_id = folder_id or self._saved_folder_id(payload.get('source_kind'))
            if folder_id not in SAVED_FOLDER_IDS:
                raise ValueError('Saved Files only supports preset folders')
            payload['folder_id'] = folder_id
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
                if payload['scope'] == 'saved':
                    folder_id = folder_id or self._saved_folder_id(payload.get('source_kind'))
                    if folder_id not in SAVED_FOLDER_IDS:
                        raise ValueError('Saved Files only supports preset folders')
                    payload['folder_id'] = folder_id
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

    def resolve_folder(self, scope: str, folder: str) -> str:
        """Resolve a user-supplied virtual folder name/path without creating folders."""
        value = str(folder or '').strip().strip('/')
        if not value:
            return ''
        if scope not in ('saved', 'shared'):
            raise ValueError('Folder is not available for this artifact type')
        with self._connect() as conn:
            if value.startswith('saved:') or value.startswith('shared:'):
                row = conn.execute('SELECT folder_id FROM artifact_folders WHERE folder_id=? AND scope=?',
                                   (value, scope)).fetchone()
                if not row:
                    raise ValueError('Unknown folder for file space')
                return row['folder_id']
            parent = None
            for name in value.split('/'):
                name = name.strip()
                if not name or name in ('.', '..') or '\\' in name:
                    raise ValueError('Invalid folder path')
                row = conn.execute("""SELECT folder_id FROM artifact_folders WHERE scope=?
                    AND IFNULL(parent_id, '')=? AND name=? COLLATE NOCASE""",
                    (scope, parent or '', name)).fetchone()
                if not row:
                    raise ValueError(f'Unknown {scope} folder: {name}')
                parent = row['folder_id']
            return parent or ''

    def create_folder(self, scope, name, parent_id=''):
        if scope != 'shared':
            raise ValueError('Only Shared Files supports folder management')
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
        if current['scope'] != 'shared':
            raise ValueError('Only Shared Files supports folder management')
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
        if folder['scope'] != 'shared':
            raise ValueError('Only Shared Files supports folder management')
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
            if payload['scope'] == 'saved' and not folder['preset']:
                raise ValueError('Saved Files only supports preset folders')
        payload['folder_id'] = folder_id or ('saved:inbox' if payload['scope'] == 'saved' else None)
        return self.save(payload)
