"""Durable transfer facts. Progress calculations and cancellation stay in TransferService."""

from datetime import datetime


class TransferHistoryStore:
    COLUMNS = (
        'transfer_id', 'client_id', 'hostname', 'direction', 'filename',
        'source_path', 'destination_path', 'state', 'stage', 'total_bytes',
        'transferred_bytes', 'artifact_id', 'error', 'started_at', 'completed_at',
    )

    def __init__(self, database):
        self.database = database
        with self.database.transaction() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS transfer_records (
                transfer_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL,
                filename TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                destination_path TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT '',
                total_bytes INTEGER,
                transferred_bytes INTEGER NOT NULL DEFAULT 0,
                artifact_id TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT ''
            )''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_transfer_records_time '
                         'ON transfer_records(started_at DESC, transfer_id DESC)')
            # A Server restart cannot resume existing TCP/file-transfer operations.
            now = datetime.now().isoformat()
            conn.execute('''UPDATE transfer_records
                SET state = 'interrupted', stage = 'interrupted', completed_at = ?,
                    error = 'Server restarted before transfer completed'
                WHERE state = 'running' ''', (now,))

    def record_started(self, item: dict):
        columns = ', '.join(self.COLUMNS)
        placeholders = ', '.join('?' for _ in self.COLUMNS)
        with self.database.transaction() as conn:
            conn.execute(f'INSERT INTO transfer_records ({columns}) VALUES ({placeholders})',
                         tuple(item.get(key) for key in self.COLUMNS))

    def record_terminal(self, item: dict):
        with self.database.transaction() as conn:
            result = conn.execute('''UPDATE transfer_records SET
                hostname = ?, direction = ?, filename = ?, source_path = ?,
                destination_path = ?, state = ?, stage = ?, total_bytes = ?,
                transferred_bytes = ?, artifact_id = ?, error = ?, completed_at = ?
                WHERE transfer_id = ? AND state = 'running' ''', (
                item.get('hostname', ''), item.get('direction', ''), item.get('filename', ''),
                item.get('source_path', ''), item.get('destination_path', ''),
                item.get('state', ''), item.get('stage', ''), item.get('total_bytes'),
                item.get('transferred_bytes', 0), item.get('artifact_id', ''),
                item.get('error', ''), item.get('completed_at', ''), item.get('transfer_id', ''),
            ))
            if result.rowcount != 1:
                raise RuntimeError('Transfer history record is missing or already finished')

    @staticmethod
    def _public_row(row):
        if row is None:
            return None
        item = dict(row)
        total = item.get('total_bytes')
        done = item.get('transferred_bytes') or 0
        item.update({
            'updated_at': item.get('completed_at') or item.get('started_at'),
            'percent': round(done * 100 / total, 1) if total and total > 0 else None,
            'progress_supported': True,
            'cancel_supported': False,
            'speed_bytes_per_sec': 0,
            'eta_seconds': None,
            'metadata': {},
        })
        return item

    @staticmethod
    def _recent_where(machine_id: str) -> tuple[str, tuple]:
        where = "state != 'running'"
        if machine_id:
            where += (' AND EXISTS (SELECT 1 FROM connection_sessions cs '
                      'WHERE cs.client_id = transfer_records.client_id AND cs.machine_id = ?)')
        return where, (machine_id,) if machine_id else ()

    def count_recent(self, machine_id: str = '') -> int:
        where, params = self._recent_where(machine_id)
        row = self.database.connection().execute(
            f'SELECT COUNT(*) FROM transfer_records WHERE {where}', params,
        ).fetchone()
        return int(row[0])

    def list_recent(self, *, limit: int = 20, offset: int = 0, machine_id: str = '') -> list[dict]:
        where, params = self._recent_where(machine_id)
        rows = self.database.connection().execute(
            f'SELECT * FROM transfer_records WHERE {where} '
            'ORDER BY started_at DESC, transfer_id DESC LIMIT ? OFFSET ?',
            (*params, limit, offset),
        ).fetchall()
        return [self._public_row(row) for row in rows]

    def get(self, transfer_id: str) -> dict | None:
        row = self.database.connection().execute(
            'SELECT * FROM transfer_records WHERE transfer_id = ?', (transfer_id,),
        ).fetchone()
        return self._public_row(row)

    def delete(self, transfer_id: str) -> bool:
        with self.database.transaction() as conn:
            result = conn.execute('''DELETE FROM transfer_records
                WHERE transfer_id = ? AND state != 'running' ''', (transfer_id,))
            return result.rowcount > 0

    def clear_recent(self, machine_id: str = '') -> int:
        where, params = self._recent_where(str(machine_id or '').strip())
        with self.database.transaction() as conn:
            result = conn.execute(f'DELETE FROM transfer_records WHERE {where}', params)
            return result.rowcount
