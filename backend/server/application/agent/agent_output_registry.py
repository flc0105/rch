"""SQLite catalog for Server-built Agent output binaries."""

from contextlib import closing, contextmanager
from datetime import datetime
import os
import sqlite3
from typing import Optional


class AgentOutputRegistry:
    DB_NAME = 'agent_outputs.sqlite3'
    FIELDS = (
        'file_name', 'builder', 'build_version', 'source', 'created_at',
        'target_os', 'target_arch', 'listener_id', 'listener_name_snapshot',
        'connect_host', 'connect_port', 'web_scheme', 'web_host', 'web_port',
    )

    def __init__(self, output_dir: str):
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.db_path = os.path.join(self.output_dir, self.DB_NAME)
        with self._connection() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            with conn:
                conn.execute('''CREATE TABLE IF NOT EXISTS agent_outputs (
                    file_name TEXT PRIMARY KEY,
                    builder TEXT NOT NULL,
                    build_version TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    target_os TEXT NOT NULL,
                    target_arch TEXT NOT NULL,
                    listener_id TEXT NOT NULL,
                    listener_name_snapshot TEXT NOT NULL,
                    connect_host TEXT NOT NULL,
                    connect_port INTEGER NOT NULL,
                    web_scheme TEXT NOT NULL,
                    web_host TEXT NOT NULL,
                    web_port INTEGER NOT NULL
                )''')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_outputs_created ON agent_outputs(created_at DESC, file_name DESC)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_outputs_listener ON agent_outputs(listener_id, created_at DESC)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_outputs_source ON agent_outputs(source)')

    @contextmanager
    def _connection(self):
        # Each request gets its own connection for Web and cleanup threads.
        with closing(sqlite3.connect(self.db_path, timeout=15)) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    @staticmethod
    def _normalize_filename(filename: str) -> str:
        name = str(filename or '').strip()
        if (not name or name in {'.', '..'} or name.startswith('.') or
                name in {AgentOutputRegistry.DB_NAME, AgentOutputRegistry.DB_NAME + '-wal',
                         AgentOutputRegistry.DB_NAME + '-shm'} or
                os.path.basename(name) != name or '/' in name or '\\' in name):
            raise ValueError('Invalid file name')
        return name

    def _safe_join_output(self, filename: str) -> str:
        file_path = os.path.abspath(os.path.join(self.output_dir, self._normalize_filename(filename)))
        if os.path.dirname(file_path) != self.output_dir:
            raise ValueError('Invalid file name')
        return file_path

    @staticmethod
    def _port(value) -> int:
        return int(value or 0)

    @staticmethod
    def _to_record(row: sqlite3.Row, size: int) -> dict:
        data = dict(row)
        # Keep the existing Agent Outputs API without storing duplicate aliases.
        return {
            'file_name': data['file_name'],
            'size': size,
            'build_time': data['created_at'],
            'build_version': data['build_version'],
            'builder': data['builder'],
            'source': data['source'],
            'target_os': data['target_os'],
            'target_arch': data['target_arch'],
            'listener_id': data['listener_id'],
            'listener_name': data['listener_name_snapshot'],
            'server_host': data['connect_host'],
            'server_port': data['connect_port'],
            'server_web_scheme': data['web_scheme'],
            'server_web_host': data['web_host'],
            'web_port': data['web_port'],
            'warnings': [],
        }

    def register_output(self, build_result: dict, *, source: str = 'manual', request_payload: Optional[dict] = None) -> dict:
        payload = dict(request_payload or {})
        filename = self._normalize_filename(build_result.get('file_name'))
        file_path = self._safe_join_output(filename)
        os.stat(file_path)  # A successful build must have produced its binary before registration.
        created_at = datetime.now().isoformat()
        values = (
            filename,
            str(build_result.get('builder') or payload.get('builder') or '').strip(),
            str(build_result.get('build_version') or '').strip(),
            str(source or payload.get('source') or 'manual').strip(),
            created_at,
            str(build_result.get('target_os') or payload.get('target_os') or '').strip(),
            str(build_result.get('target_arch') or payload.get('target_arch') or '').strip(),
            str(payload.get('listener_id') or '').strip(),
            str(payload.get('listener_name') or '').strip(),
            str(payload.get('server_host') or '').strip(),
            self._port(payload.get('server_port')),
            str(payload.get('server_web_scheme') or 'http').strip(),
            str(payload.get('server_web_host') or payload.get('server_host') or '').strip(),
            self._port(payload.get('web_port')),
        )
        columns = ', '.join(self.FIELDS)
        placeholders = ', '.join('?' for _ in self.FIELDS)
        update = ', '.join(f'{column}=excluded.{column}' for column in self.FIELDS if column != 'file_name')
        with self._connection() as conn:
            with conn:
                conn.execute(f'INSERT INTO agent_outputs ({columns}) VALUES ({placeholders}) '
                             f'ON CONFLICT(file_name) DO UPDATE SET {update}', values)
        return self.get_output_record(filename)

    def get_output_record(self, filename: str) -> dict:
        filename = self._normalize_filename(filename)
        with self._connection() as conn:
            row = conn.execute('SELECT * FROM agent_outputs WHERE file_name=?', (filename,)).fetchone()
        if row is None:
            raise FileNotFoundError('Agent output is not registered')
        try:
            size = os.stat(self._safe_join_output(filename)).st_size
        except FileNotFoundError:
            raise FileNotFoundError('File not found') from None
        return self._to_record(row, size)

    def list_outputs(self) -> list:
        with self._connection() as conn:
            rows = conn.execute('SELECT * FROM agent_outputs ORDER BY created_at DESC, file_name DESC').fetchall()
        results = []
        for row in rows:
            try:
                size = os.stat(self._safe_join_output(row['file_name'])).st_size
            except FileNotFoundError:
                continue
            results.append(self._to_record(row, size))
        return results

    def delete_output(self, filename: str) -> dict:
        filename = self._normalize_filename(filename)
        file_path = self._safe_join_output(filename)
        with self._connection() as conn:
            row = conn.execute('SELECT 1 FROM agent_outputs WHERE file_name=?', (filename,)).fetchone()
        if row is None:
            raise FileNotFoundError('Agent output is not registered')
        os.remove(file_path)
        with self._connection() as conn:
            with conn:
                conn.execute('DELETE FROM agent_outputs WHERE file_name=?', (filename,))
        return {'deleted': True, 'file_name': filename}
