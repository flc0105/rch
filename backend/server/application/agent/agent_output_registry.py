"""SQLite catalog for Server-built Agent output binaries."""

from datetime import datetime
import os
import sqlite3
from typing import Optional


class AgentOutputRegistry:
    FIELDS = (
        'file_name', 'builder', 'build_version', 'connection_mode',
        'transport', 'listener_id', 'listener_name_snapshot', 'target_os',
        'target_arch', 'build_origin', 'endpoint_ip', 'endpoint_port',
        'web_ip', 'web_port', 'created_at',
    )

    def __init__(self, output_dir: str, database):
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.database = database

    @staticmethod
    def _normalize_filename(filename: str) -> str:
        name = str(filename or '').strip()
        if (not name or name in {'.', '..'} or name.startswith('.') or
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
        return {
            **data,
            'listener_name': data['listener_name_snapshot'] if data['connection_mode'] == 'reverse' else '',
            'size': size,
            'build_time': data['created_at'],
            'warnings': [],
        }

    def register_output(self, build_result: dict, *, source: str = 'manual', request_payload: Optional[dict] = None) -> dict:
        payload = dict(request_payload or {})
        filename = self._normalize_filename(build_result.get('file_name'))
        file_path = self._safe_join_output(filename)
        os.stat(file_path)  # A successful build must have produced its binary before registration.
        mode = str(payload.get('connection_mode') or '').strip()
        transport = str(payload.get('listener_protocol') or '').strip()
        if mode not in ('reverse', 'bind'):
            raise ValueError('Invalid Agent connection mode')
        if transport not in ('tcp', 'mtls_tcp'):
            raise ValueError('Invalid Agent transport')
        builder = str(build_result.get('builder') or payload.get('builder') or '').strip()
        # Bind listens locally; Reverse connects to the selected Server listener.
        endpoint_ip = str(payload.get('bind_host' if mode == 'bind' else 'server_host') or '').strip()
        endpoint_port = self._port(payload.get('bind_port' if mode == 'bind' else 'server_port'))
        if not endpoint_ip or not 1 <= endpoint_port <= 65535:
            raise ValueError('Invalid Agent endpoint')
        show_web = mode == 'reverse' or builder == 'go_loader'
        web_ip = (
            str(payload.get('server_web_host') or (payload.get('server_host') if mode == 'reverse' else '') or '').strip()
            if show_web else ''
        )
        web_port = self._port(payload.get('web_port')) if show_web else 0
        if show_web and (not web_ip or not 1 <= web_port <= 65535):
            raise ValueError('Invalid Agent web endpoint')
        created_at = datetime.now().isoformat()
        values = (
            filename,
            builder,
            str(build_result.get('build_version') or '').strip(),
            mode,
            transport,
            str(payload.get('listener_id') or '').strip() if mode == 'reverse' else '',
            str(payload.get('listener_name') or '').strip() if mode == 'reverse' else '',
            str(build_result['target_os'] if 'target_os' in build_result else payload.get('target_os') or '').strip(),
            str(build_result['target_arch'] if 'target_arch' in build_result else payload.get('target_arch') or '').strip(),
            str(source or payload.get('source') or 'manual').strip(),
            endpoint_ip,
            endpoint_port,
            web_ip,
            web_port,
            created_at,
        )
        columns = ', '.join(self.FIELDS)
        placeholders = ', '.join('?' for _ in self.FIELDS)
        update = ', '.join(f'{column}=excluded.{column}' for column in self.FIELDS if column != 'file_name')
        with self.database.transaction() as conn:
            conn.execute(f'INSERT INTO agent_outputs ({columns}) VALUES ({placeholders}) '
                             f'ON CONFLICT(file_name) DO UPDATE SET {update}', values)
        return self.get_output_record(filename)

    def get_output_record(self, filename: str) -> dict:
        filename = self._normalize_filename(filename)
        conn = self.database.connection()
        row = conn.execute('SELECT * FROM agent_outputs WHERE file_name=?', (filename,)).fetchone()
        if row is None:
            raise FileNotFoundError('Agent output is not registered')
        try:
            size = os.stat(self._safe_join_output(filename)).st_size
        except FileNotFoundError:
            raise FileNotFoundError('File not found') from None
        return self._to_record(row, size)

    def list_outputs(self) -> list:
        conn = self.database.connection()
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
        conn = self.database.connection()
        row = conn.execute('SELECT 1 FROM agent_outputs WHERE file_name=?', (filename,)).fetchone()
        if row is None:
            raise FileNotFoundError('Agent output is not registered')
        os.remove(file_path)
        with self.database.transaction() as conn:
            conn.execute('DELETE FROM agent_outputs WHERE file_name=?', (filename,))
        return {'deleted': True, 'file_name': filename}
