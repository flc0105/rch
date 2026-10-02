import threading
from datetime import datetime

from core.utils.json_utils import json_dumps_or_default, json_loads_or_default
from server.application.jobs.background_job_view_service import BackgroundJobViewService
from server.models.records import LifecycleRecordBase, OutputRecordBase


class BackgroundJobStore:
    """
    SQLite-backed background job ledger.

    Responsibilities:
    - Persist job instances, messages, and artifact associations.
    - Scope durable history by machine_id while retaining the reporting client_id.
    - Keep summary queries lightweight and load messages/files only for details.
    """

    ACTIVE_STATES = ('running', 'stopping')

    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()
        self.artifact_service = None
        self.view_service = BackgroundJobViewService(self)
        self.mark_active_jobs_interrupted()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat()

    def _row_to_job(self, row) -> dict | None:
        if row is None:
            return None

        item = dict(row)
        item['command_id'] = item.get('command_id')
        if 'message_count' in item:
            item['message_count'] = int(item.get('message_count', 0) or 0)
        if 'file_count' in item:
            item['file_count'] = int(item.get('file_count', 0) or 0)
        item['params'] = json_loads_or_default(item.pop('params_json', '{}'), {})
        return item

    def _build_default_job(self, payload: dict) -> dict:
        job_id = str(payload.get('job_id') or '').strip()
        created_at = str(payload.get('time') or self._now_iso())
        lifecycle = LifecycleRecordBase(
            machine_id=str(payload.get('machine_id') or '').strip(),
            client_id=str(payload.get('client_id') or '').strip(),
            hostname=str(payload.get('hostname') or '').strip(),
            addr=str(payload.get('addr') or '').strip(),
            created_at=created_at,
            started_at='',
            updated_at=created_at,
            finished_at='',
        ).to_dict()
        return {
            **lifecycle,
            'job_id': job_id,
            'job_name': str(payload.get('job_name') or '').strip(),
            'job_key': str(payload.get('job_key') or '').strip(),
            'thread_name': str(payload.get('thread_name') or '').strip(),
            'command_id': payload.get('command_id'),
            'execution_mode': str(payload.get('execution_mode') or 'inproc').strip() or 'inproc',
            'state': 'unknown',
            'params': dict(payload.get('params') or {}) if isinstance(payload.get('params'), dict) else {},
        }

    @staticmethod
    def _build_file_snapshot(file_info: dict, job: dict | None = None) -> dict:
        source = dict(file_info or {}) if isinstance(file_info, dict) else {}
        job_item = dict(job or {}) if isinstance(job, dict) else {}
        return {
            'artifact_id': str(source.get('artifact_id') or ''),
            'artifact_type': str(source.get('artifact_type') or ''),
            'category': str(source.get('category') or ''),
            'hostname': str(source.get('hostname') or job_item.get('hostname') or ''),
            'machine_id': str(source.get('machine_id') or job_item.get('machine_id') or ''),
            'client_id': str(source.get('client_id') or job_item.get('client_id') or ''),
            'original_name': str(source.get('original_name') or ''),
            'stored_name': str(source.get('stored_name') or ''),
            'relative_path': str(source.get('relative_path') or source.get('saved_path') or ''),
            'size': int(source.get('size', 0) or 0),
            'download_url': str(source.get('download_url') or ''),
            'raw_url': str(source.get('raw_url') or ''),
            'preview_url': str(source.get('preview_url') or ''),
        }

    def backfill_file_snapshots(self, artifacts: list[dict] | None) -> int:
        """Backfill old associations while their Artifact metadata still exists."""
        artifact_map = {
            str(item.get('artifact_id') or '').strip(): item
            for item in (artifacts or [])
            if isinstance(item, dict) and str(item.get('artifact_id') or '').strip()
        }
        if not artifact_map:
            return 0

        updated = 0
        with self._lock, self.database.transaction() as conn:
            rows = conn.execute(
                '''
                SELECT f.association_id, f.artifact_id,
                       b.machine_id, b.client_id, b.hostname
                FROM background_job_files f
                JOIN background_jobs b ON b.job_id = f.job_id
                WHERE f.snapshot_json = '' OR f.snapshot_json = '{}'
                '''
            ).fetchall()
            for row in rows:
                artifact = artifact_map.get(str(row['artifact_id'] or '').strip())
                if artifact is None:
                    continue
                snapshot = self._build_file_snapshot(
                    artifact,
                    {
                        'machine_id': row['machine_id'],
                        'client_id': row['client_id'],
                        'hostname': row['hostname'],
                    },
                )
                conn.execute(
                    'UPDATE background_job_files SET snapshot_json = ? WHERE association_id = ?',
                    (json_dumps_or_default(snapshot, '{}'), int(row['association_id'])),
                )
                updated += 1
        return updated

    def _ensure_job(self, conn, payload: dict) -> dict:
        job_id = str(payload.get('job_id') or '').strip()
        client_id = str(payload.get('client_id') or '').strip()
        if not client_id:
            raise ValueError('client_id is required')
        if not job_id:
            raise ValueError('job_id is required')

        row = conn.execute('SELECT * FROM background_jobs WHERE job_id = ?', (job_id,)).fetchone()
        if row is None:
            job = self._build_default_job(payload)
            conn.execute(
                '''
                INSERT INTO background_jobs(
                    job_id, machine_id, client_id, hostname, addr, job_name, job_key,
                    thread_name, command_id, execution_mode, state, created_at, started_at,
                    updated_at, finished_at, params_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    job['job_id'], job['machine_id'], job['client_id'], job['hostname'], job['addr'],
                    job['job_name'], job['job_key'], job['thread_name'], job['command_id'],
                    job['execution_mode'], job['state'], job['created_at'], job['started_at'],
                    job['updated_at'], job['finished_at'], json_dumps_or_default(job['params']),
                ),
            )
        else:
            existing = self._row_to_job(row) or {}
            event_time = str(payload.get('time') or self._now_iso())
            updates = {
                'machine_id': str(payload.get('machine_id') or existing.get('machine_id') or '').strip(),
                'client_id': client_id or str(existing.get('client_id') or '').strip(),
                'hostname': str(payload.get('hostname') or existing.get('hostname') or '').strip(),
                'addr': str(payload.get('addr') or existing.get('addr') or '').strip(),
                'job_name': str(payload.get('job_name') or existing.get('job_name') or '').strip(),
                'job_key': str(payload.get('job_key') or existing.get('job_key') or '').strip(),
                'thread_name': str(payload.get('thread_name') or existing.get('thread_name') or '').strip(),
                'command_id': payload.get('command_id', existing.get('command_id')),
                'execution_mode': str(
                    payload.get('execution_mode') or existing.get('execution_mode') or 'inproc'
                ).strip() or 'inproc',
                'params': (
                    dict(payload.get('params') or existing.get('params') or {})
                    if isinstance(payload.get('params'), dict)
                    else dict(existing.get('params') or {})
                ),
                'updated_at': event_time,
            }
            conn.execute(
                '''
                UPDATE background_jobs
                SET machine_id = ?, client_id = ?, hostname = ?, addr = ?, job_name = ?, job_key = ?,
                    thread_name = ?, command_id = ?, execution_mode = ?, params_json = ?, updated_at = ?
                WHERE job_id = ?
                ''',
                (
                    updates['machine_id'], updates['client_id'], updates['hostname'], updates['addr'],
                    updates['job_name'], updates['job_key'], updates['thread_name'], updates['command_id'],
                    updates['execution_mode'], json_dumps_or_default(updates['params']),
                    updates['updated_at'], job_id,
                ),
            )

        return self._row_to_job(
            conn.execute('SELECT * FROM background_jobs WHERE job_id = ?', (job_id,)).fetchone()
        )

    def _select_job_row(self, job_id: str, machine_id: str = '', client_id: str = ''):
        job_id_text = str(job_id or '').strip()
        machine_id_text = str(machine_id or '').strip()
        client_id_text = str(client_id or '').strip()
        if not job_id_text:
            return None

        conn = self.database.connection()
        if machine_id_text:
            return conn.execute(
                'SELECT * FROM background_jobs WHERE job_id = ? AND machine_id = ?',
                (job_id_text, machine_id_text),
            ).fetchone()
        if client_id_text:
            return conn.execute(
                'SELECT * FROM background_jobs WHERE job_id = ? AND client_id = ?',
                (job_id_text, client_id_text),
            ).fetchone()
        return conn.execute('SELECT * FROM background_jobs WHERE job_id = ?', (job_id_text,)).fetchone()

    def mark_active_jobs_interrupted(self):
        now = self._now_iso()
        with self._lock, self.database.transaction() as conn:
            conn.execute(
                '''
                UPDATE background_jobs
                SET state = 'interrupted', finished_at = CASE WHEN finished_at = '' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE state IN ('running', 'stopping')
                ''',
                (now, now),
            )

    def apply_status_report(self, payload: dict) -> dict:
        with self._lock, self.database.transaction() as conn:
            job = self._ensure_job(conn, payload)
            state = str(payload.get('state') or '').strip() or str(job.get('state') or 'unknown')
            event_time = str(payload.get('time') or self._now_iso())
            started_at = str(job.get('started_at') or '')
            finished_at = str(job.get('finished_at') or '')

            if state == 'running' and not started_at:
                started_at = event_time
            if state == 'running':
                finished_at = ''
            if state in ('stopped', 'error', 'interrupted') and not finished_at:
                finished_at = event_time

            conn.execute(
                '''
                UPDATE background_jobs
                SET state = ?, started_at = ?, updated_at = ?, finished_at = ?
                WHERE job_id = ?
                ''',
                (state, started_at, event_time, finished_at, job['job_id']),
            )
            return self._row_to_job(
                conn.execute('SELECT * FROM background_jobs WHERE job_id = ?', (job['job_id'],)).fetchone()
            )

    def append_message_report(self, payload: dict) -> dict:
        with self._lock, self.database.transaction() as conn:
            job = self._ensure_job(conn, payload)
            event_time = str(payload.get('time') or self._now_iso())
            output = OutputRecordBase(
                status=int(payload.get('status', 1) or 0),
                text=str(payload.get('text') or ''),
                eof=int(payload.get('eof', 0) or 0),
                created_at=event_time,
            )

            conn.execute(
                '''
                INSERT INTO background_job_messages(job_id, status, text, eof, created_at)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (job['job_id'], output.status, output.text, output.eof, output.created_at),
            )

            state = str(job.get('state') or 'unknown')
            finished_at = str(job.get('finished_at') or '')
            if state == 'interrupted':
                state = 'running'
                finished_at = ''

            conn.execute(
                '''
                UPDATE background_jobs
                SET updated_at = ?, state = ?, finished_at = ?
                WHERE job_id = ?
                ''',
                (event_time, state, finished_at, job['job_id']),
            )
            return self._row_to_job(
                conn.execute('SELECT * FROM background_jobs WHERE job_id = ?', (job['job_id'],)).fetchone()
            )

    def append_file_report(self, payload: dict) -> dict:
        with self._lock, self.database.transaction() as conn:
            job = self._ensure_job(conn, payload)
            file_info = payload.get('file') or {}
            if not isinstance(file_info, dict):
                file_info = {}

            artifact_id = str(file_info.get('artifact_id') or '').strip()
            event_time = str(payload.get('time') or self._now_iso())
            if artifact_id:
                snapshot_json = json_dumps_or_default(self._build_file_snapshot(file_info, job), '{}')
                conn.execute(
                    '''
                    INSERT OR IGNORE INTO background_job_files(job_id, artifact_id, created_at, snapshot_json)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (job['job_id'], artifact_id, event_time, snapshot_json),
                )
                conn.execute(
                    '''
                    UPDATE background_job_files
                    SET snapshot_json = ?
                    WHERE job_id = ? AND artifact_id = ?
                    ''',
                    (snapshot_json, job['job_id'], artifact_id),
                )

            state = str(job.get('state') or 'unknown')
            finished_at = str(job.get('finished_at') or '')
            if state == 'interrupted':
                state = 'running'
                finished_at = ''

            conn.execute(
                '''
                UPDATE background_jobs
                SET updated_at = ?, state = ?, finished_at = ?
                WHERE job_id = ?
                ''',
                (event_time, state, finished_at, job['job_id']),
            )
            return self._row_to_job(
                conn.execute('SELECT * FROM background_jobs WHERE job_id = ?', (job['job_id'],)).fetchone()
            )

    @staticmethod
    def _summary_select(where_clause: str) -> str:
        return f'''
            SELECT b.*,
                   (SELECT COUNT(*) FROM background_job_messages m WHERE m.job_id = b.job_id) AS message_count,
                   (SELECT COUNT(*) FROM background_job_files f WHERE f.job_id = b.job_id) AS file_count
            FROM background_jobs b
            WHERE {where_clause}
            ORDER BY b.updated_at DESC, b.job_id DESC
        '''

    def list_raw_jobs(self, machine_id: str = '', client_id: str = '') -> list[dict]:
        machine_id_text = str(machine_id or '').strip()
        client_id_text = str(client_id or '').strip()
        conn = self.database.connection()

        if machine_id_text:
            rows = conn.execute(self._summary_select('b.machine_id = ?'), (machine_id_text,)).fetchall()
        elif client_id_text:
            rows = conn.execute(self._summary_select('b.client_id = ?'), (client_id_text,)).fetchall()
        else:
            rows = []

        return [self._row_to_job(row) for row in rows]

    def get_raw_job(self, job_id: str, machine_id: str = '', client_id: str = '') -> dict | None:
        row = self._select_job_row(job_id, machine_id=machine_id, client_id=client_id)
        job = self._row_to_job(row)
        if job is None:
            return None

        conn = self.database.connection()
        message_rows = conn.execute(
            '''
            SELECT message_id, status, text, eof, created_at
            FROM background_job_messages
            WHERE job_id = ?
            ORDER BY message_id ASC
            ''',
            (job['job_id'],),
        ).fetchall()
        file_rows = conn.execute(
            '''
            SELECT association_id, artifact_id, created_at, snapshot_json
            FROM background_job_files
            WHERE job_id = ?
            ORDER BY association_id ASC
            ''',
            (job['job_id'],),
        ).fetchall()

        job['messages'] = [
            OutputRecordBase(
                seq=int(row['message_id']),
                status=int(row['status'] or 0),
                text=str(row['text'] or ''),
                eof=int(row['eof'] or 0),
                created_at=str(row['created_at'] or ''),
            ).to_dict()
            for row in message_rows
        ]
        job['files'] = []
        for row in file_rows:
            snapshot = json_loads_or_default(row['snapshot_json'], {})
            if not isinstance(snapshot, dict):
                snapshot = {}
            snapshot['association_id'] = int(row['association_id'])
            snapshot['artifact_id'] = str(row['artifact_id'] or snapshot.get('artifact_id') or '')
            snapshot['created_at'] = str(row['created_at'] or '')
            job['files'].append(snapshot)
        return job

    def delete_job(self, job_id: str, machine_id: str = '', client_id: str = '') -> dict | None:
        with self._lock, self.database.transaction() as conn:
            row = None
            job_id_text = str(job_id or '').strip()
            machine_id_text = str(machine_id or '').strip()
            client_id_text = str(client_id or '').strip()
            if machine_id_text:
                row = conn.execute(
                    'SELECT * FROM background_jobs WHERE job_id = ? AND machine_id = ?',
                    (job_id_text, machine_id_text),
                ).fetchone()
            elif client_id_text:
                row = conn.execute(
                    'SELECT * FROM background_jobs WHERE job_id = ? AND client_id = ?',
                    (job_id_text, client_id_text),
                ).fetchone()
            if row is None:
                return None

            job = self._row_to_job(row)
            conn.execute('DELETE FROM background_jobs WHERE job_id = ?', (job_id_text,))
            return job

    def get_jobs_for_scope(self, machine_id: str = '', client_id: str = '') -> list[dict]:
        return self.view_service.get_jobs_for_scope(machine_id=machine_id, client_id=client_id)

    def get_job_for_scope(self, job_id: str, machine_id: str = '', client_id: str = '') -> dict | None:
        return self.view_service.get_job_for_scope(job_id, machine_id=machine_id, client_id=client_id)
