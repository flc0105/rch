"""SQLite index for Server artifacts; logical folders never move underlying files."""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime


from core.artifact_contract import (
    ArtifactScope, SAVED_CATEGORY_FOLDERS, SAVED_FOLDER_IDS, normalize_saved_category,
    SAVED_CATEGORY_BY_FOLDER_ID, saved_folder_id, saved_category_for_folder,
)


class ArtifactSqliteCatalog:
    """The only runtime metadata source: files remain on disk, paths are independent of folders."""

    def __init__(self, database):
        self.database = database
        # The unified rch.db schema is owned exclusively by RchDatabase.
        with self.database.transaction() as conn:
            for kind, name in SAVED_CATEGORY_FOLDERS.items():
                conn.execute('''INSERT OR IGNORE INTO artifact_folders
                    (folder_id, scope, parent_id, name, preset, created_at)
                    VALUES (?, ?, NULL, ?, 1, ?)''',
                    (SAVED_FOLDER_IDS[kind], ArtifactScope.SAVED.value, name,
                     datetime.now().isoformat(timespec='seconds')))

    @contextmanager
    def _connect(self, *, write=False):
        if write:
            with self.database.transaction() as conn:
                yield conn
        else:
            yield self.database.connection()

    @staticmethod
    def _public_payload(payload):
        """Derive the Saved folder from its only classification field."""
        if payload['scope'] == ArtifactScope.SAVED.value:
            payload['folder_id'] = saved_folder_id(payload['category'])
        return payload

    @staticmethod
    def _stored_payload(payload):
        stored = dict(payload)
        if 'source_kind' in stored or '_meta_path' in stored:
            raise ValueError('Obsolete Artifact metadata fields: source_kind or _meta_path')
        if stored['scope'] == ArtifactScope.SAVED.value:
            folder_id = stored.pop('folder_id', None)
            stored['category'] = normalize_saved_category(stored.get('category')).value
            canonical_id = saved_folder_id(stored['category'])
            if folder_id and folder_id != canonical_id:
                raise ValueError('Saved folder must match category')
        else:
            if 'category' in stored:
                raise ValueError('Only Saved Files can have category')
            if stored['scope'] == ArtifactScope.PREVIEW.value and stored.get('folder_id'):
                raise ValueError('Preview cache does not support folders')
        return stored

    def get(self, artifact_id):
        with self._connect() as conn:
            row = conn.execute('SELECT payload_json FROM artifact_entries WHERE artifact_id=?', (artifact_id,)).fetchone()
        return self._public_payload(json.loads(row['payload_json'])) if row else None

    def list(self, *, scope='', folder_id='', machine_id='', category='', search=''):
        if folder_id in SAVED_CATEGORY_BY_FOLDER_ID:
            if scope and scope != ArtifactScope.SAVED.value:
                raise ValueError('Saved folder belongs only to Saved Files')
            scope = ArtifactScope.SAVED.value
        where, params = [], []
        if scope:
            ArtifactScope(scope)
            where.append('scope=?')
            params.append(scope)
        else:
            where.append('scope!=?')
            params.append(ArtifactScope.PREVIEW.value)
        if folder_id:
            if scope == ArtifactScope.SAVED.value:
                requested_kind = saved_category_for_folder(folder_id).value
                if category and normalize_saved_category(category).value != requested_kind:
                    raise ValueError('Saved folder and category must match')
                category = requested_kind
            else:
                where.append('folder_id=?')
                params.append(folder_id)
        if category:
            if scope and scope != ArtifactScope.SAVED.value:
                raise ValueError('Only Saved Files can be filtered by category')
            category = normalize_saved_category(category).value
            where.append('category=?')
            params.append(category)
        if machine_id:
            where.append('machine_id=?')
            params.append(machine_id)
        if search:
            where.append('payload_json LIKE ?')
            params.append('%' + search + '%')
        condition = ' WHERE ' + ' AND '.join(where) if where else ''
        with self._connect() as conn:
            rows = conn.execute('SELECT payload_json FROM artifact_entries' + condition +
                                ' ORDER BY saved_at DESC, artifact_id DESC', params).fetchall()
        return [self._public_payload(json.loads(row['payload_json'])) for row in rows]

    def save(self, payload):
        stored = self._stored_payload(payload)
        scope = ArtifactScope(stored['scope'])
        folder_id = stored.get('folder_id') or None
        with self._connect(write=True) as conn:
            if folder_id:
                folder = conn.execute('SELECT scope FROM artifact_folders WHERE folder_id=?',
                                      (folder_id,)).fetchone()
                if not folder or folder['scope'] != scope.value:
                    raise ValueError('Folder does not belong to this file space')
            conn.execute('''INSERT INTO artifact_entries
                (artifact_id, scope, folder_id, category, machine_id, saved_at, saved_path, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    scope=excluded.scope, folder_id=excluded.folder_id,
                    category=excluded.category, machine_id=excluded.machine_id,
                    saved_at=excluded.saved_at, saved_path=excluded.saved_path,
                    payload_json=excluded.payload_json''',
                (stored['artifact_id'], scope.value, folder_id, stored.get('category'),
                 stored.get('machine_id', ''), stored['saved_at'], stored['saved_path'],
                 json.dumps(stored, ensure_ascii=False)))
        return self._public_payload(dict(stored))

    def import_records(self, records):
        '''Atomically import canonical records, leaving existing artifact IDs unchanged.'''
        imported, already = 0, 0
        with self._connect(write=True) as conn:
            for payload in records:
                stored = self._stored_payload(payload)
                existing = conn.execute('SELECT saved_path FROM artifact_entries WHERE artifact_id=?',
                                        (stored['artifact_id'],)).fetchone()
                if existing:
                    if existing['saved_path'] != stored['saved_path']:
                        raise ValueError(f"Artifact ID conflict: {stored['artifact_id']}")
                    already += 1
                    continue
                folder_id = stored.get('folder_id') or None
                if folder_id:
                    folder = conn.execute('SELECT scope FROM artifact_folders WHERE folder_id=?',
                                          (folder_id,)).fetchone()
                    if not folder or folder['scope'] != stored['scope']:
                        raise ValueError(f"Invalid folder for imported artifact: {stored['artifact_id']}")
                conn.execute('''INSERT INTO artifact_entries
                    (artifact_id, scope, folder_id, category, machine_id, saved_at, saved_path, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (stored['artifact_id'], stored['scope'], folder_id, stored.get('category'),
                     stored.get('machine_id', ''), stored['saved_at'], stored['saved_path'],
                     json.dumps(stored, ensure_ascii=False)))
                imported += 1
        return imported, already

    def delete(self, artifact_id):
        with self._connect(write=True) as conn:
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
        if ArtifactScope(scope) not in (ArtifactScope.SAVED, ArtifactScope.SHARED):
            raise ValueError('Folder is not available for this artifact type')
        with self._connect() as conn:
            if value in SAVED_CATEGORY_BY_FOLDER_ID or conn.execute(
                    'SELECT 1 FROM artifact_folders WHERE folder_id=? AND scope=?', (value, scope)).fetchone():
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
        if scope != ArtifactScope.SHARED.value:
            raise ValueError('Only Shared Files supports folder management')
        name = str(name or '').strip()
        if not name or name in ('.', '..') or '/' in name or '\\' in name or len(name) > 120:
            raise ValueError('Invalid folder name')
        folder_id = uuid.uuid4().hex
        with self._connect(write=True) as conn:
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
        if current['scope'] != ArtifactScope.SHARED.value:
            raise ValueError('Only Shared Files supports folder management')
        if current['preset']:
            raise ValueError('Preset folders cannot be renamed')
        name = str(name or '').strip()
        if not name or '/' in name or '\\' in name or len(name) > 120:
            raise ValueError('Invalid folder name')
        with self._connect(write=True) as conn:
            if conn.execute('''SELECT 1 FROM artifact_folders WHERE scope=?
                AND IFNULL(parent_id,'')=? AND name=? COLLATE NOCASE AND folder_id!=?''',
                (current['scope'], current['parent_id'] or '', name, folder_id)).fetchone():
                raise ValueError('Folder already exists')
            conn.execute('UPDATE artifact_folders SET name=? WHERE folder_id=?', (name, folder_id))
        return self.get_folder(folder_id)

    def delete_folder(self, folder_id):
        folder = self.get_folder(folder_id)
        if folder['scope'] != ArtifactScope.SHARED.value:
            raise ValueError('Only Shared Files supports folder management')
        if folder['preset']:
            raise ValueError('Preset folders cannot be deleted')
        with self._connect(write=True) as conn:
            if conn.execute('SELECT 1 FROM artifact_entries WHERE folder_id=?', (folder_id,)).fetchone() or \
               conn.execute('SELECT 1 FROM artifact_folders WHERE parent_id=?', (folder_id,)).fetchone():
                raise ValueError('Folder must be empty')
            conn.execute('DELETE FROM artifact_folders WHERE folder_id=?', (folder_id,))
        return {'folder_id': folder_id}

    def move(self, artifact_id, folder_id):
        payload = self.get(artifact_id)
        if payload is None:
            raise FileNotFoundError('Artifact not found')
        if payload['scope'] != ArtifactScope.SHARED.value:
            raise ValueError('Only Shared Files supports moving artifacts')
        if folder_id:
            folder = self.get_folder(folder_id)
            if folder['scope'] != ArtifactScope.SHARED.value:
                raise ValueError('Folder does not belong to Shared Files')
        payload['folder_id'] = folder_id or None
        return self.save(payload)
