import json
import threading
from datetime import datetime

from server.application.jobs.background_job_view_service import BackgroundJobViewService


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

    def _now_iso(self) -> str:
        return datetime.now().isoformat()

    def _json_dumps(self, value) -> str:
        try:
            return json.dumps(value if value is not None else {}, ensure_ascii=False)
        except Exception:
            return '{}'

    def _json_loads(self, value, default=None):
        fallback = {} if default is None else default
        try:
            parsed = json.loads(str(value or ''))
            return parsed
        except Exception:
            return fallback

    def _row_to_job(self, row) -> dict | None:
        if row is None:
            return None

        item = dict(row)
        item['command_id'] = item.get('command_id')
        item['message_count'] = int(item.get('message_count', 0) or 0)
        item['file_count'] = int(item.get('file_count', 0) or 0)
        item['params'] = self._json_loads(item.pop('params_json', '{}'), {})
        return item

    def _build_default_job(self, payload: dict) -> dict:
        job_id = str(payload.get('job_id') or '').strip()
        job_name = str(payload.get('job_name') or '').strip()
        job_key = str(payload.get('job_key') or '').strip()
        created_at = str(payload.get('time') or self._now_iso())
        display_base = job_key or job_name or 'job'
        display_name = str(payload.get('display_name') or '').strip()
        if not display_name:
            display_name = f'{display_base}#{job_id[:8]}' if job_id else display_base

        return {
            'job_id': job_id,
            'machine_id': str(payload.get('machine_id') or '').strip(),
            'client_id': str(payload.get('client_id') or '').strip(),
            'hostname': str(payload.get('hostname') or '').strip(),
            'job_name': job_name,
            'job_key': job_key,
            'display_name': display_name,
            'thread_name': str(payload.get('thread_name') or '').strip(),
            'command_id': payload.get('command_id'),
            'execution_mode': str(payload.get('execution_mode') or 'inproc').strip() or 'inproc',
            'state': 'unknown',
            'created_at': created_at,
            'started_at': '',
            'stopped_at': '',
            'updated_at': created_at,
            'last_message': '',
            'message_count': 0,
            'file_count': 0,
            'params': dict(payload.get('params') or {}) if isinstance(payload.get('params'), dict) else {},
        }

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
                    job_id, machine_id, client_id, hostname, job_name, job_key, display_name,
                    thread_name, command_id, execution_mode, state, created_at, started_at,
                    stopped_at, updated_at, last_message, message_count, file_count, params_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    job['job_id'], job['machine_id'], job['client_id'], job['hostname'],
                    job['job_name'], job['job_key'], job['display_name'], job['thread_name'],
                    job['command_id'], job['execution_mode'], job['state'], job['created_at'],
                    job['started_at'], job['stopped_at'], job['updated_at'], job['last_message'],
                    job['message_count'], job['file_count'], self._json_dumps(job['params']),
                ),
            )
        else:
            existing = self._row_to_job(row) or {}
            event_time = str(payload.get('time') or self._now_iso())
            updates = {
                'machine_id': str(payload.get('machine_id') or existing.get('machine_id') or '').strip(),
                'client_id': client_id or str(existing.get('client_id') or '').strip(),
                'hostname': str(payload.get('hostname') or existing.get('hostname') or '').strip(),
                'job_name': str(payload.get('job_name') or existing.get('job_name') or '').strip(),
                'job_key': str(payload.get('job_key') or existing.get('job_key') or '').strip(),
                'display_name': str(payload.get('display_name') or existing.get('display_name') or '').strip(),
                'thread_name': str(payload.get('thread_name') or existing.get('thread_name') or '').strip(),
                'command_id': payload.get('command_id', existing.get('command_id')),
                'execution_mode': str(payload.get('execution_mode') or existing.get('execution_mode') or 'inproc').strip() or 'inproc',
                'params': dict(payload.get('params') or existing.get('params') or {}) if isinstance(payload.get('params'), dict) else dict(existing.get('params') or {}),
                'updated_at': event_time,
            }
            conn.execute(
                '''
                UPDATE background_jobs
                SET machine_id = ?, client_id = ?, hostname = ?, job_name = ?, job_key = ?,
                    display_name = ?, thread_name = ?, command_id = ?, execution_mode = ?,
                    params_json = ?, updated_at = ?
                WHERE job_id = ?
                ''',
                (
                    updates['machine_id'], updates['client_id'], updates['hostname'],
                    updates['job_name'], updates['job_key'], updates['display_name'],
                    updates['thread_name'], updates['command_id'], updates['execution_mode'],
                    self._json_dumps(updates['params']), updates['updated_at'], job_id,
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
                SET state = 'interrupted', stopped_at = CASE WHEN stopped_at = '' THEN ? ELSE stopped_at END,
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
            stopped_at = str(job.get('stopped_at') or '')

            if state == 'running' and not started_at:
                started_at = event_time
            if state == 'running':
                stopped_at = ''
            if state in ('stopped', 'error') and not stopped_at:
                stopped_at = event_time

            status_text = str(payload.get('text') or '').strip()
            last_message = status_text or str(job.get('last_message') or '')

            conn.execute(
                '''
                UPDATE background_jobs
                SET state = ?, started_at = ?, stopped_at = ?, updated_at = ?, last_message = ?
                WHERE job_id = ?
                ''',
                (state, started_at, stopped_at, event_time, last_message, job['job_id']),
            )
            return self._row_to_job(
                conn.execute('SELECT * FROM background_jobs WHERE job_id = ?', (job['job_id'],)).fetchone()
            )

    def append_message_report(self, payload: dict) -> dict:
        with self._lock, self.database.transaction() as conn:
            job = self._ensure_job(conn, payload)
            event_time = str(payload.get('time') or self._now_iso())
            status = int(payload.get('status', 1) or 0)
            text = str(payload.get('text') or '')
            eof = int(payload.get('eof', 0) or 0)
            created_at = self._now_iso()

            conn.execute(
                '''
                INSERT INTO background_job_messages(job_id, status, text, eof, event_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (job['job_id'], status, text, eof, event_time, created_at),
            )

            state = str(job.get('state') or 'unknown')
            stopped_at = str(job.get('stopped_at') or '')
            if state == 'interrupted':
                state = 'running'
                stopped_at = ''

            conn.execute(
                '''
                UPDATE background_jobs
                SET message_count = message_count + 1, last_message = ?, updated_at = ?,
                    state = ?, stopped_at = ?
                WHERE job_id = ?
                ''',
                (text, event_time, state, stopped_at, job['job_id']),
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
            inserted = False
            if artifact_id:
                cursor = conn.execute(
                    '''
                    INSERT OR IGNORE INTO background_job_files(job_id, artifact_id, event_time, created_at)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (job['job_id'], artifact_id, event_time, self._now_iso()),
                )
                inserted = cursor.rowcount > 0

            state = str(job.get('state') or 'unknown')
            stopped_at = str(job.get('stopped_at') or '')
            if state == 'interrupted':
                state = 'running'
                stopped_at = ''

            conn.execute(
                '''
                UPDATE background_jobs
                SET file_count = file_count + ?, updated_at = ?, state = ?, stopped_at = ?
                WHERE job_id = ?
                ''',
                (1 if inserted else 0, event_time, state, stopped_at, job['job_id']),
            )
            return self._row_to_job(
                conn.execute('SELECT * FROM background_jobs WHERE job_id = ?', (job['job_id'],)).fetchone()
            )

    def list_raw_jobs(self, machine_id: str = '', client_id: str = '') -> list[dict]:
        machine_id_text = str(machine_id or '').strip()
        client_id_text = str(client_id or '').strip()
        conn = self.database.connection()

        if machine_id_text:
            rows = conn.execute(
                'SELECT * FROM background_jobs WHERE machine_id = ? ORDER BY updated_at DESC, job_id DESC',
                (machine_id_text,),
            ).fetchall()
        elif client_id_text:
            rows = conn.execute(
                'SELECT * FROM background_jobs WHERE client_id = ? ORDER BY updated_at DESC, job_id DESC',
                (client_id_text,),
            ).fetchall()
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
            SELECT message_id, status, text, eof, event_time
            FROM background_job_messages
            WHERE job_id = ?
            ORDER BY message_id ASC
            ''',
            (job['job_id'],),
        ).fetchall()
        file_rows = conn.execute(
            '''
            SELECT association_id, artifact_id, event_time
            FROM background_job_files
            WHERE job_id = ?
            ORDER BY association_id ASC
            ''',
            (job['job_id'],),
        ).fetchall()

        job['messages'] = [
            {
                'message_id': int(row['message_id']),
                'status': int(row['status'] or 0),
                'text': str(row['text'] or ''),
                'eof': int(row['eof'] or 0),
                'time': str(row['event_time'] or ''),
            }
            for row in message_rows
        ]
        job['files'] = [
            {
                'association_id': int(row['association_id']),
                'artifact_id': str(row['artifact_id'] or ''),
                'time': str(row['event_time'] or ''),
            }
            for row in file_rows
        ]
        job['message_count'] = len(job['messages'])
        job['file_count'] = len(job['files'])
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
