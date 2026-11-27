"""Artifact metadata index in rch.db; Saved folders are computed, not stored."""
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from core.utils.logger import logger
from core.artifact_contract import (
    ArtifactType, SAVED_CATEGORY_FOLDERS, SAVED_FOLDER_IDS, SAVED_CATEGORY_BY_FOLDER_ID,
    saved_folder_id, saved_category_for_folder, normalize_saved_category,
)

COLUMNS = ('artifact_id','artifact_type','folder_id','original_name','size','category',
           'machine_id','saved_at','saved_path','client_id','source_command_id','extra')

class ArtifactSqliteCatalog:
    def __init__(self, database, storage_root):
        self.database = database
        self.storage_root = Path(storage_root).resolve()

    @staticmethod
    def object_relative_path(artifact_id):
        value = str(artifact_id or '')
        if len(value) != 32 or any(ch not in '0123456789abcdef' for ch in value):
            raise ValueError('Invalid Artifact ID')
        return Path('objects') / value[:2] / value

    @contextmanager
    def _connect(self, *, write=False):
        if write:
            with self.database.transaction() as conn:
                yield conn
        else:
            yield self.database.connection()

    def _relative_path(self, value):
        value = str(value or '')
        path = Path(value)
        if path.is_absolute():
            path = path.resolve().relative_to(self.storage_root)
        if not path.parts or any(part in ('', '.', '..') for part in path.parts):
            raise ValueError('Invalid Artifact saved_path')
        physical = (self.storage_root / path).resolve()
        if not physical.is_relative_to(self.storage_root):
            raise ValueError('Artifact path escapes storage root')
        return path.as_posix()

    def physical_path(self, value):
        relative = self._relative_path(value)
        return str((self.storage_root / relative).resolve())

    @staticmethod
    def _urls(artifact_id):
        return {'download_url': f'/api/artifacts/{artifact_id}/download',
                'raw_url': f'/api/artifacts/{artifact_id}/raw',
                'preview_url': f'/api/artifacts/{artifact_id}/preview'}

    def _row_to_artifact(self, row):
        if row is None:
            return None
        item = dict(row)
        item['extra'] = json.loads(item['extra'] or '{}')
        if item['saved_path'] != self.object_relative_path(item['artifact_id']).as_posix():
            raise ValueError('Artifact storage path does not match ID')
        item['stored_name'] = item['artifact_id']
        if item['category'] is None:
            item.pop('category')
        if item['artifact_type'] == ArtifactType.SAVED.value:
            item['folder_id'] = saved_folder_id(item['category'])
        item.update(self._urls(item['artifact_id']))
        return item

    def _as_record(self, payload):
        item = dict(payload)
        if any(k in item for k in ('scope','payload_json','source_kind','_meta_path','hostname','addr','updated_at','status_text')):
            raise ValueError('Unsupported Artifact metadata fields')
        kind = ArtifactType(item['artifact_type']).value
        category = None
        folder_id = item.get('folder_id') or None
        if kind == 'saved':
            category = normalize_saved_category(item.get('category')).value
            if folder_id and folder_id != saved_folder_id(category):
                raise ValueError('Saved folder must match category')
            folder_id = None
        else:
            if 'category' in item:
                raise ValueError('Only Saved Files can have category')
            if kind == 'preview' and folder_id:
                raise ValueError('Preview cache does not support folders')
        extra = item.get('extra') or {}
        if not isinstance(extra, dict):
            raise ValueError('Artifact extra must be an object')
        artifact_id = str(item['artifact_id'])
        if self._relative_path(item['saved_path']) != self.object_relative_path(artifact_id).as_posix():
            raise ValueError('Artifact storage path does not match ID')
        return (artifact_id, kind, folder_id, str(item['original_name']),
                int(item.get('size') or 0), category, str(item.get('machine_id') or ''),
                str(item['saved_at']), self._relative_path(item['saved_path']),
                str(item.get('client_id') or ''),
                None if item.get('source_command_id') is None else str(item['source_command_id']),
                json.dumps(extra, ensure_ascii=False))

    def object_ids(self):
        # Include every catalog row, including previews and malformed metadata.
        with self._connect() as conn:
            return {row[0] for row in conn.execute('SELECT artifact_id FROM artifact_entries')}

    def has_object_id(self, artifact_id):
        with self._connect() as conn:
            return conn.execute('SELECT 1 FROM artifact_entries WHERE artifact_id=?', (artifact_id,)).fetchone() is not None

    def get(self, artifact_id):
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM artifact_entries WHERE artifact_id=?',(artifact_id,)).fetchone()
        return self._row_to_artifact(row)

    def list(self, *, artifact_type='', folder_id='', machine_id='', category='', search=''):
        clauses, params = [], []
        if artifact_type:
            clauses.append('artifact_type=?'); params.append(ArtifactType(artifact_type).value)
        else:
            clauses.append('artifact_type!=?');params.append('preview')
        if folder_id:
            if folder_id in SAVED_CATEGORY_BY_FOLDER_ID:
                if artifact_type and artifact_type != 'saved': raise ValueError('Folder belongs to Saved Files')
                target_category = saved_category_for_folder(folder_id).value
                if category and normalize_saved_category(category).value != target_category:
                    raise ValueError('Saved folder and category must match')
                clauses.extend(('artifact_type=?','category=?'));params.extend(('saved',target_category))
            else:
                clauses.append('folder_id=?');params.append(folder_id)
        if category and folder_id not in SAVED_CATEGORY_BY_FOLDER_ID:
            if artifact_type and artifact_type!='saved':raise ValueError('Only Saved Files can be filtered by category')
            clauses.append('category=?');params.append(normalize_saved_category(category).value)
        if machine_id:
            clauses.append('machine_id=?');params.append(machine_id)
        if search:
            clauses.append('(original_name LIKE ? OR category LIKE ? OR extra LIKE ?)')
            params.extend(('%'+search+'%',)*3)
        condition=' WHERE '+' AND '.join(clauses) if clauses else ''
        with self._connect() as conn:
            rows=conn.execute('SELECT * FROM artifact_entries'+condition+' ORDER BY saved_at DESC, artifact_id DESC',params).fetchall()
        items = []
        for row in rows:
            try:
                items.append(self._row_to_artifact(row))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                logger.warning('Skipping invalid Artifact row %s: %s', row['artifact_id'], exc)
        return items

    def shared_file_names(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT folder_id, original_name FROM artifact_entries WHERE artifact_type='shared'").fetchall()
        return {(row['folder_id'] or '', row['original_name']) for row in rows}

    def shared_file_exists(self, folder_id, name):
        with self._connect() as conn:
            return bool(conn.execute("SELECT 1 FROM artifact_entries WHERE artifact_type='shared' AND folder_id IS ? AND original_name=? LIMIT 1", (folder_id or None, name)).fetchone())

    def _verify_folder(self, conn, folder_id):
        if folder_id and not conn.execute('SELECT 1 FROM artifact_folders WHERE folder_id=?',(folder_id,)).fetchone():
            raise ValueError('Invalid Shared folder')

    def save(self,payload):
        record=self._as_record(payload)
        with self._connect(write=True) as conn:
            if record[1]=='shared':self._verify_folder(conn,record[2])
            cols=','.join(COLUMNS)
            conn.execute(f'''INSERT INTO artifact_entries ({cols}) VALUES ({','.join('?' for _ in COLUMNS)})
                ON CONFLICT(artifact_id) DO UPDATE SET {','.join(f'{col}=excluded.{col}' for col in COLUMNS[1:])}''',record)
        return self.get(record[0])

    def import_records(self,records):
        imported=already=0
        with self._connect(write=True) as conn:
            for payload in records:
                record=self._as_record(payload)
                row=conn.execute('SELECT saved_path FROM artifact_entries WHERE artifact_id=?',(record[0],)).fetchone()
                if row:
                    if row['saved_path']!=record[8]:raise ValueError('Artifact ID conflict: '+record[0])
                    already+=1;continue
                if record[1]=='shared': self._verify_folder(conn,record[2])
                conn.execute(f"INSERT INTO artifact_entries ({','.join(COLUMNS)}) VALUES ({','.join('?' for _ in COLUMNS)})",record)
                imported+=1
        return imported,already

    def delete(self,artifact_id):
        with self._connect(write=True) as conn:
            conn.execute('DELETE FROM artifact_entries WHERE artifact_id=?',(artifact_id,))

    def list_folders(self,artifact_type=''):
        with self._connect() as conn:
            rows=conn.execute('SELECT * FROM artifact_folders ORDER BY name COLLATE NOCASE').fetchall() if artifact_type!='saved' else []
        shared=[{**dict(row),'artifact_type':'shared','is_preset':False} for row in rows]
        saved=[{'folder_id':SAVED_FOLDER_IDS[cat],'parent_id':None,'name':name,
                'artifact_type':'saved','is_preset':True} for cat,name in SAVED_CATEGORY_FOLDERS.items()]
        return saved+shared if not artifact_type else (saved if artifact_type=='saved' else shared if artifact_type=='shared' else [])

    def _validate_parent(self,conn,parent_id):
        if parent_id:self._verify_folder(conn,parent_id)

    def resolve_folder(self,artifact_type,folder):
        value=str(folder or '').strip().strip('/')
        if not value:return ''
        if ArtifactType(artifact_type)!=ArtifactType.SHARED:raise ValueError('Only Shared folder paths can be resolved')
        with self._connect() as conn:
            if conn.execute('SELECT 1 FROM artifact_folders WHERE folder_id=?',(value,)).fetchone():return value
            parent=None
            for name in value.split('/'):
                name=name.strip()
                if not name or name in ('.','..') or '\\\\' in name:raise ValueError('Invalid folder path')
                row=conn.execute('''SELECT folder_id FROM artifact_folders WHERE IFNULL(parent_id,'')=? AND name=? COLLATE NOCASE''', (parent or '',name)).fetchone()
                if row is None:raise ValueError('Unknown Shared folder: '+name)
                parent=row['folder_id']
            return parent or ''

    def create_folder(self,artifact_type,name,parent_id=''):
        if artifact_type!='shared':raise ValueError('Only Shared Files supports folders')
        name=str(name or '').strip()
        if not name or name in ('.','..') or '/' in name or '\\\\' in name or len(name)>120:raise ValueError('Invalid folder name')
        ident=uuid.uuid4().hex
        with self._connect(write=True) as conn:
            self._validate_parent(conn,parent_id)
            if conn.execute('''SELECT 1 FROM artifact_folders WHERE IFNULL(parent_id,'')=? AND name=? COLLATE NOCASE''',(parent_id or '',name)).fetchone():raise ValueError('Folder already exists')
            conn.execute('INSERT INTO artifact_folders(folder_id,parent_id,name,created_at) VALUES(?,?,?,?)',
                         (ident,parent_id or None,name,datetime.now().isoformat(timespec='seconds')))
        return self.get_folder(ident)

    def get_folder(self,folder_id):
        with self._connect() as conn:
            row=conn.execute('SELECT * FROM artifact_folders WHERE folder_id=?',(folder_id,)).fetchone()
        if not row:raise FileNotFoundError('Folder not found')
        return {**dict(row),'artifact_type':'shared','is_preset':False}

    def rename_folder(self,folder_id,name):
        self.get_folder(folder_id)
        name=str(name or '').strip()
        if not name or name in ('.','..') or '/' in name or '\\\\' in name or len(name)>120:raise ValueError('Invalid folder name')
        with self._connect(write=True) as conn:
            row=conn.execute('SELECT parent_id FROM artifact_folders WHERE folder_id=?',(folder_id,)).fetchone()
            if conn.execute('''SELECT 1 FROM artifact_folders WHERE IFNULL(parent_id,'')=? AND name=? COLLATE NOCASE AND folder_id!=?''', (row['parent_id'] or '',name,folder_id)).fetchone():raise ValueError('Folder already exists')
            conn.execute('UPDATE artifact_folders SET name=? WHERE folder_id=?',(name,folder_id))
        return self.get_folder(folder_id)

    def shared_tree(self, folder_id=''):
        """Return Shared file IDs and descendant folder IDs (children before parents)."""
        with self._connect() as conn:
            folders = conn.execute('SELECT folder_id, parent_id FROM artifact_folders').fetchall()
            files = conn.execute("SELECT artifact_id, folder_id FROM artifact_entries WHERE artifact_type=?",
                                 (ArtifactType.SHARED.value,)).fetchall()
        known = {row['folder_id'] for row in folders}
        if folder_id and folder_id not in known:
            raise FileNotFoundError('Folder not found')
        children = {}
        for row in folders:
            children.setdefault(row['parent_id'] or '', []).append(row['folder_id'])
        pending = list(children.get(folder_id, ()))
        ordered = []
        visited = {folder_id}
        while pending:
            current = pending.pop()
            if current in visited:
                raise ValueError('Invalid Shared folder tree')
            visited.add(current)
            ordered.append(current)
            pending.extend(children.get(current, ()))
        if not folder_id and len(ordered) != len(folders):
            raise ValueError('Invalid Shared folder tree')
        artifact_ids = [row['artifact_id'] for row in files if (row['folder_id'] or '') in visited]
        return artifact_ids, list(reversed(ordered))

    def delete_folder(self,folder_id):
        self.get_folder(folder_id)
        with self._connect(write=True) as conn:
            if conn.execute('SELECT 1 FROM artifact_entries WHERE folder_id=?',(folder_id,)).fetchone() or conn.execute('SELECT 1 FROM artifact_folders WHERE parent_id=?',(folder_id,)).fetchone():raise ValueError('Folder contents changed during deletion')
            conn.execute('DELETE FROM artifact_folders WHERE folder_id=?',(folder_id,))
        return {'folder_id':folder_id}

    def move(self,artifact_id,folder_id):
        item=self.get(artifact_id)
        if item is None:raise FileNotFoundError('Artifact not found')
        if item['artifact_type']!='shared':raise ValueError('Only Shared Files supports moving')
        item['folder_id']=folder_id or None
        return self.save(item)
