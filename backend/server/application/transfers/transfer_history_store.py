"""Durable transfer facts. Progress calculations and cancellation stay in TransferService."""

from datetime import datetime


class TransferHistoryStore:
    COLUMNS = (
        'transfer_id', 'batch_id', 'client_id', 'hostname', 'direction', 'filename',
        'source_path', 'destination_path', 'state', 'stage', 'total_bytes',
        'transferred_bytes', 'artifact_id', 'error', 'started_at', 'completed_at',
    )

    def __init__(self, database):
        self.database = database
        with self.database.transaction() as conn:
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

    def list_batch_members(self, batch_id: str) -> list[dict]:
        rows = self.database.connection().execute(
            'SELECT * FROM transfer_records WHERE batch_id = ? ORDER BY started_at, transfer_id',
            (batch_id,)).fetchall()
        return [self._public_row(row) for row in rows]

    def get(self, transfer_id: str) -> dict | None:
        row = self.database.connection().execute(
            'SELECT * FROM transfer_records WHERE transfer_id = ?', (transfer_id,),
        ).fetchone()
        return self._public_row(row)

    def delete(self, transfer_id: str) -> bool:
        with self.database.transaction() as conn:
            result = conn.execute('''DELETE FROM transfer_records
                WHERE transfer_id = ? AND state != 'running' AND batch_id = '' ''', (transfer_id,))
            return result.rowcount > 0

    @staticmethod
    def _filter(machine_id, alias):
        if not machine_id:
            return '', ()
        return (f" AND EXISTS (SELECT 1 FROM connection_sessions cs WHERE "
                f"cs.client_id = {alias}.client_id AND cs.machine_id = ?)", (machine_id,))

    def list_recent(self, *, limit, offset, machine_id, batch_lookup):
        cond, params = self._filter(machine_id, 'rows')
        sql = ("SELECT transfer_id, is_batch FROM ("
               "SELECT transfer_id, client_id, started_at, 0 AS is_batch "
               "FROM transfer_records WHERE state != 'running' AND batch_id = '' "
               "UNION ALL SELECT batch_id AS transfer_id, client_id, started_at, 1 AS is_batch "
               "FROM transfer_batches WHERE state != 'running') AS rows WHERE 1=1" + cond)
        db = self.database.connection()
        count = db.execute('SELECT COUNT(*) FROM (' + sql + ')', params).fetchone()[0]
        rows = db.execute(sql + ' ORDER BY started_at DESC, transfer_id DESC LIMIT ? OFFSET ?',
                          (*params, limit, offset)).fetchall()
        recent = [batch_lookup(row['transfer_id']) if row['is_batch'] else self.get(row['transfer_id'])
                  for row in rows]
        return recent, count

    def clear_recent(self, machine_id):
        cond, params = self._filter(machine_id, 'transfer_batches')
        with self.database.transaction() as conn:
            rows = conn.execute("SELECT batch_id FROM transfer_batches WHERE state != 'running'" + cond,
                                params).fetchall()
            for row in rows:
                conn.execute("DELETE FROM transfer_records WHERE batch_id = ? AND state != 'running'",
                             (row['batch_id'],))
            parents = conn.execute("DELETE FROM transfer_batches WHERE state != 'running'" + cond,
                                   params).rowcount
            cond, params = self._filter(machine_id, 'transfer_records')
            singles = conn.execute("DELETE FROM transfer_records WHERE state != 'running' AND batch_id = ''" + cond,
                                   params).rowcount
            return parents + singles
