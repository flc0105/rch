"""Durable parent identity and lifecycle for browser upload batches."""

from datetime import datetime

from server.application.connection.connection_history_store import ConnectionHistoryStore


class TransferBatchStore:
    TERMINAL = ('completed', 'failed', 'cancelled', 'interrupted')

    def __init__(self, database, history):
        self.database = database
        self.history = history
        self.connections = ConnectionHistoryStore(database)
        self._cancelling = set()
        self._members = {}
        self._planned_directories = {}
        with database.transaction() as conn:
            # Server restarts interrupt all in-flight operations; unsubmitted
            # members are also accounted for in the final parent result.
            conn.execute("""UPDATE transfer_batches SET state = 'interrupted',
                submission_closed = 1, completed_at = ?, error = 'Server restarted during upload'
                WHERE state = 'running'""", (datetime.now().isoformat(),))

    def start(self, *, batch_id, client_id, tab_id, destination_path, total_files, directories, members):
        with self.database.transaction() as conn:
            conn.execute("""INSERT INTO transfer_batches
                (batch_id, client_id, tab_id, destination_path, total_files, folder_count, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (batch_id, client_id, tab_id, destination_path, total_files,
                 0, datetime.now().isoformat()))
        self._members[batch_id] = members
        self._planned_directories[batch_id] = directories
        return self.get(batch_id)

    def matches_plan(self, batch_id, members, directories):
        return (self._members.get(batch_id) == members
                and self._planned_directories.get(batch_id) == directories)

    def validate_member(self, batch_id, *, client_id, tab_id, total_files, batch_index, destination_path, filename, size, conflict_policy):
        row = self.database.connection().execute(
            'SELECT * FROM transfer_batches WHERE batch_id = ?', (batch_id,)).fetchone()
        if (not row or row['client_id'] != client_id or row['tab_id'] != tab_id
                or row['submission_closed'] or row['total_files'] != total_files):
            raise ValueError('Upload batch not found, closed or mismatched')
        count = self.database.connection().execute(
            'SELECT COUNT(*) FROM transfer_records WHERE batch_id = ?', (batch_id,)).fetchone()[0]
        if count >= total_files or batch_index != count:
            raise ValueError('Upload batch member index is duplicate or out of sequence')
        members = self._members.get(batch_id)
        if members is None:
            raise ValueError('Upload batch plan is unavailable')
        expected = members[batch_index]
        if (destination_path, filename, size, conflict_policy) != (expected.destination_path, expected.filename, expected.size, expected.conflict_policy):
            raise ValueError('Upload batch member does not match its plan')

    def finalize(self, batch_id, *, client_id, tab_id, folder_count, error):
        with self.database.transaction() as conn:
            batch = conn.execute('SELECT * FROM transfer_batches WHERE batch_id = ?', (batch_id,)).fetchone()
            if not batch or batch['client_id'] != client_id or batch['tab_id'] != tab_id:
                raise ValueError('Upload batch not found or mismatched')
            if not batch['submission_closed']:
                planned = len(self._planned_directories[batch_id]) if batch_id in self._planned_directories else batch['folder_count']
                if not 0 <= folder_count <= planned:
                    raise ValueError('Invalid completed folder count')
                if folder_count != planned and not error:
                    error = 'Incomplete folder preparation'
                conn.execute("""UPDATE transfer_batches SET submission_closed = 1,
                    folder_count = ?, error = ? WHERE batch_id = ?""",
                    (folder_count, error, batch_id))
        return self.refresh(batch_id)

    def request_cancel(self, batch_id):
        batch = self.get(batch_id)
        if not batch or batch['state'] != 'running':
            raise ValueError('Upload batch is no longer active')
        self._cancelling.add(batch_id)
        return self.finalize(batch_id, client_id=batch['client_id'], tab_id=batch['tab_id'],
                             folder_count=batch['folder_count'], error='Upload batch cancelled')

    @staticmethod
    def _counts(conn, batch_id):
        return conn.execute("""SELECT COUNT(*) AS submitted,
            COALESCE(SUM(state = 'completed'),0) AS completed,
            COALESCE(SUM(state = 'running'),0) AS active,
            COALESCE(SUM(state = 'failed'),0) AS failed,
            COALESCE(SUM(state = 'cancelled'),0) AS cancelled,
            COALESCE(SUM(state = 'interrupted'),0) AS interrupted,
            COALESCE(SUM(total_bytes),0) AS submitted_bytes,
            COALESCE(SUM(CASE WHEN state = 'completed' THEN total_bytes ELSE 0 END),0) AS completed_bytes
            FROM transfer_records WHERE batch_id = ?""", (batch_id,)).fetchone()

    def refresh(self, batch_id):
        with self.database.transaction() as conn:
            batch = conn.execute('SELECT * FROM transfer_batches WHERE batch_id = ?', (batch_id,)).fetchone()
            if not batch:
                return None
            counts = self._counts(conn, batch_id)
            # A file-only plan can close automatically. Directory preparation must
            # explicitly report its actual outcome before the parent can finish.
            if batch['state'] == 'running' and not counts['active'] and (
                    batch['submission_closed'] or (not self._planned_directories.get(batch_id) and batch['total_files'] > 0 and counts['submitted'] == batch['total_files'])):
                if batch_id in self._cancelling:
                    state = 'cancelled'
                elif counts['completed'] == batch['total_files'] and not batch['error']:
                    state = 'completed'
                elif counts['interrupted'] and not counts['failed']:
                    state = 'interrupted'
                elif counts['cancelled'] and not counts['failed'] and counts['submitted'] == batch['total_files']:
                    state = 'cancelled'
                else:
                    state = 'failed'
                conn.execute("""UPDATE transfer_batches SET state = ?, submission_closed = 1, completed_at = ?
                    WHERE batch_id = ? AND state = 'running'""",
                    (state, datetime.now().isoformat(), batch_id))
                self._cancelling.discard(batch_id)
                self._members.pop(batch_id, None)
                self._planned_directories.pop(batch_id, None)
        return self.get(batch_id)

    def get(self, batch_id):
        conn = self.database.connection()
        row = conn.execute('SELECT * FROM transfer_batches WHERE batch_id = ?', (batch_id,)).fetchone()
        if not row:
            return None
        counts = self._counts(conn, batch_id)
        device = conn.execute("""SELECT hostname FROM transfer_records
            WHERE batch_id = ? AND hostname != '' ORDER BY started_at DESC LIMIT 1""", (batch_id,)).fetchone()
        hostname = device['hostname'] if device else self.connections.get_identity_by_client_id(row['client_id'])[1]
        failed = conn.execute("""SELECT filename, error, state FROM transfer_records
            WHERE batch_id = ? AND state IN ('failed', 'cancelled', 'interrupted')
            ORDER BY CASE WHEN state = 'failed' THEN 0 ELSE 1 END, started_at LIMIT 1""", (batch_id,)).fetchone()
        errors = [f"{failed['filename']}: {failed['error'] or failed['state']}"] if failed else []
        if row['error'] and row['error'] not in errors:
            errors.append(row['error'])
        total = row['total_files']; done = counts['completed']
        planned = self._members.get(batch_id)
        # The full plan is available while active; after completion the durable
        # member sizes are sufficient only when every planned member was registered.
        planned_bytes = (sum(member.size for member in planned) if planned is not None else
                         counts['submitted_bytes'] if counts['submitted'] == total else None)
        return {
            'transfer_id': 'batch:' + batch_id, 'batch_id': batch_id, 'is_batch': True,
            'client_id': row['client_id'], 'tab_id': row['tab_id'],
            'hostname': hostname, 'filename': 'Batch upload', 'direction': 'server_to_client',
            'source_path': '', 'destination_path': row['destination_path'],
            'state': row['state'], 'stage': 'cancelling' if batch_id in self._cancelling else row['state'],
            'error': ' · '.join(errors), 'total_files': total, 'folder_count': row['folder_count'],
            'submitted_files': counts['submitted'], 'completed_files': done,
            'active_files': counts['active'], 'failed_files': counts['failed'],
            'cancelled_files': counts['cancelled'], 'interrupted_files': counts['interrupted'],
            'unsubmitted_files': total - counts['submitted'],
            'submission_closed': bool(row['submission_closed']),
            'total_bytes': None, 'transferred_bytes': None,
            'planned_bytes': planned_bytes, 'submitted_bytes': counts['submitted_bytes'],
            'completed_bytes': counts['completed_bytes'],
            'percent': round(100 * done / total, 1) if total else None,
            'progress_supported': bool(total), 'cancel_supported': row['state'] == 'running',
            'speed_bytes_per_sec': 0, 'eta_seconds': None, 'metadata': {},
            'started_at': row['started_at'], 'completed_at': row['completed_at'],
        }

    def members(self, batch_id):
        return self.history.list_batch_members(batch_id)

    def active(self, tab_id):
        where = "state = 'running'" + (" AND tab_id = ?" if tab_id else '')
        rows = self.database.connection().execute(
            f'SELECT batch_id FROM transfer_batches WHERE {where}',
            (tab_id,) if tab_id else ()).fetchall()
        return [self.get(row['batch_id']) for row in rows]

    def delete(self, batch_id):
        with self.database.transaction() as conn:
            row = conn.execute("DELETE FROM transfer_batches WHERE batch_id = ? AND state != 'running'", (batch_id,))
            if not row.rowcount:
                return False
            conn.execute("DELETE FROM transfer_records WHERE batch_id = ? AND state != 'running'", (batch_id,))
        return True

