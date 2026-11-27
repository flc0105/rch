import os
import sqlite3
import shutil
import threading
from itertools import count
from contextlib import closing, contextmanager


SAVED_BIND_TARGETS_SCHEMA = """CREATE TABLE saved_bind_targets (
                target_id TEXT PRIMARY KEY,
                host TEXT NOT NULL COLLATE NOCASE,
                port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
                server_web_base_url TEXT NOT NULL,
                transport TEXT NOT NULL DEFAULT 'tcp' CHECK(transport IN ('tcp', 'mtls_tcp')),
                name TEXT NOT NULL DEFAULT '',
                machine_id TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                os_type TEXT NOT NULL DEFAULT '',
                os_ver TEXT NOT NULL DEFAULT '',
                integrity TEXT NOT NULL DEFAULT '',
                last_seen_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                last_client_id TEXT NOT NULL DEFAULT '',
                UNIQUE(host, port)
            )"""

# Canonical domain tables that can also be initialized idempotently in an
# existing database. Schema ownership belongs exclusively to persistence.
ADDITIONAL_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS activity_records (
                activity_id TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                client_id TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                action TEXT NOT NULL,
                origin TEXT NOT NULL,
                presentation TEXT NOT NULL,
                status TEXT NOT NULL,
                invocation_json TEXT NOT NULL,
                resolved_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                started_at_ms INTEGER NOT NULL,
                finished_at TEXT,
                references_json TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                result_message_bytes INTEGER NOT NULL DEFAULT 0,
                result_data_bytes INTEGER NOT NULL DEFAULT 0,
                result_omitted INTEGER NOT NULL DEFAULT 0,
                result_summary TEXT NOT NULL DEFAULT ''
            )""",
    """CREATE INDEX IF NOT EXISTS idx_activity_machine_time
                ON activity_records(machine_id, started_at_ms DESC, activity_id DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_activity_machine_status
                ON activity_records(machine_id, status, started_at_ms DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_activity_machine_kind
                ON activity_records(machine_id, kind, started_at_ms DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_activity_client_time
                ON activity_records(machine_id, client_id, started_at_ms DESC)""",
    """CREATE TABLE IF NOT EXISTS keychain_entries (
                cred_id TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                hostname TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('login', 'secret')),
                name TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                secret_ciphertext TEXT NOT NULL,
                site TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_keychain_machine_name
                ON keychain_entries(machine_id, name COLLATE NOCASE)""",
    """CREATE TABLE IF NOT EXISTS transfer_records (
                transfer_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL DEFAULT '',
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
            )""",
    """CREATE TABLE IF NOT EXISTS transfer_batches (
                batch_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                tab_id TEXT NOT NULL,
                destination_path TEXT NOT NULL DEFAULT '',
                total_files INTEGER NOT NULL,
                folder_count INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'running',
                submission_closed INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT ''
            )""",
    """CREATE INDEX IF NOT EXISTS idx_transfer_records_time ON transfer_records(started_at DESC, transfer_id DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_transfer_records_batch ON transfer_records(batch_id, started_at DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_transfer_batches_time ON transfer_batches(started_at DESC, batch_id DESC)""",
)

# Canonical persisted schema. Database initialization never rewrites existing records.
FINAL_SCHEMA_STATEMENTS = (
    'CREATE TABLE "background_job_files" (\n                association_id INTEGER PRIMARY KEY AUTOINCREMENT,\n                job_id TEXT NOT NULL,\n                artifact_id TEXT NOT NULL,\n                linked_at TEXT NOT NULL DEFAULT \'\', snapshot TEXT NOT NULL DEFAULT \'{}\',\n                FOREIGN KEY(job_id) REFERENCES "background_jobs"(job_id) ON DELETE CASCADE,\n                UNIQUE(job_id, artifact_id)\n            )',
    'CREATE TABLE "background_job_messages" (\n                message_id INTEGER PRIMARY KEY AUTOINCREMENT,\n                job_id TEXT NOT NULL,\n                status INTEGER NOT NULL DEFAULT 1,\n                text TEXT NOT NULL DEFAULT \'\',\n                eof INTEGER NOT NULL DEFAULT 0,\n                created_at TEXT NOT NULL DEFAULT \'\',\n                FOREIGN KEY(job_id) REFERENCES "background_jobs"(job_id) ON DELETE CASCADE\n            )',
    'CREATE TABLE "background_jobs" (\n                job_id TEXT PRIMARY KEY,\n                machine_id TEXT NOT NULL DEFAULT \'\',\n                client_id TEXT NOT NULL DEFAULT \'\',\n                hostname TEXT NOT NULL DEFAULT \'\',\n                addr TEXT NOT NULL DEFAULT \'\',\n                job_name TEXT NOT NULL DEFAULT \'\',\n                job_key TEXT NOT NULL DEFAULT \'\',\n                thread_name TEXT NOT NULL DEFAULT \'\',\n                command_id INTEGER,\n                execution_mode TEXT NOT NULL DEFAULT \'inproc\',\n                state TEXT NOT NULL DEFAULT \'unknown\',\n                created_at TEXT NOT NULL DEFAULT \'\',\n                started_at TEXT NOT NULL DEFAULT \'\',\n                updated_at TEXT NOT NULL DEFAULT \'\',\n                finished_at TEXT NOT NULL DEFAULT \'\',\n                params_json TEXT NOT NULL DEFAULT \'{}\'\n            )',
    "CREATE TABLE command_recents (\n                machine_id TEXT NOT NULL,\n                command TEXT NOT NULL,\n                last_used_at TEXT NOT NULL DEFAULT '',\n                last_used_at_ms INTEGER NOT NULL DEFAULT 0,\n                use_count INTEGER NOT NULL DEFAULT 1,\n                snapshot_json TEXT NOT NULL DEFAULT '{}',\n                PRIMARY KEY(machine_id, command)\n            )",
    "CREATE TABLE connection_sessions (\n                machine_id TEXT NOT NULL,\n                client_id TEXT NOT NULL,\n                connected_at TEXT NOT NULL DEFAULT '',\n                connected_at_ms INTEGER NOT NULL DEFAULT 0,\n                disconnected_at TEXT NOT NULL DEFAULT '',\n                disconnected_at_ms INTEGER NOT NULL DEFAULT 0,\n                last_seen_at TEXT NOT NULL DEFAULT '',\n                duration_ms INTEGER NOT NULL DEFAULT 0,\n                termination_reason TEXT NOT NULL DEFAULT '',\n                termination_detail TEXT NOT NULL DEFAULT '{}',\n                snapshot TEXT NOT NULL DEFAULT '{}',\n                PRIMARY KEY(machine_id, client_id)\n            )",
    'CREATE TABLE device_group_members (\n                machine_id TEXT PRIMARY KEY,\n                group_id TEXT NOT NULL,\n                FOREIGN KEY(group_id) REFERENCES device_groups(group_id) ON DELETE CASCADE\n            )',
    "CREATE TABLE device_groups (\n                group_id TEXT PRIMARY KEY,\n                name TEXT NOT NULL COLLATE NOCASE UNIQUE,\n                created_at TEXT NOT NULL DEFAULT '',\n                updated_at TEXT NOT NULL DEFAULT ''\n            )",
    "CREATE TABLE external_tool_presets (\n                preset_id TEXT PRIMARY KEY,\n                tool_id TEXT NOT NULL,\n                name TEXT NOT NULL COLLATE NOCASE,\n                params_json TEXT NOT NULL DEFAULT '{}',\n                created_at TEXT NOT NULL DEFAULT '',\n                updated_at TEXT NOT NULL DEFAULT '',\n                UNIQUE(tool_id, name)\n            )",
    "CREATE TABLE notifications (\n                id TEXT PRIMARY KEY,\n                event_id TEXT UNIQUE,\n                notification_key TEXT NOT NULL DEFAULT '',\n                type TEXT NOT NULL DEFAULT 'info',\n                title TEXT NOT NULL,\n                message TEXT NOT NULL DEFAULT '',\n                shown_at TEXT NOT NULL DEFAULT '',\n                shown_at_ms INTEGER NOT NULL DEFAULT 0,\n                context_json TEXT NOT NULL DEFAULT '{}',\n                actions_json TEXT NOT NULL DEFAULT '[]'\n            )",
    "CREATE TABLE pinned_commands (\n                machine_id TEXT NOT NULL,\n                command TEXT NOT NULL,\n                pinned_at TEXT NOT NULL,\n                pin_order INTEGER NOT NULL DEFAULT 0,\n                snapshot_json TEXT NOT NULL DEFAULT '{}',\n                PRIMARY KEY(machine_id, command)\n            )",
    "CREATE TABLE pinned_paths (\n                machine_id TEXT NOT NULL,\n                display_name TEXT NOT NULL,\n                path TEXT NOT NULL,\n                created_at TEXT NOT NULL DEFAULT '',\n                updated_at TEXT NOT NULL DEFAULT '',\n                PRIMARY KEY(machine_id, display_name)\n            )",
    "CREATE TABLE recent_devices (\n                machine_key TEXT PRIMARY KEY,\n                machine_id TEXT NOT NULL,\n                client_id TEXT NOT NULL DEFAULT '',\n                machine_order INTEGER NOT NULL DEFAULT 0,\n                connection_state TEXT NOT NULL DEFAULT 'offline',\n                last_seen_at TEXT NOT NULL DEFAULT '',\n                recent_updated_at TEXT NOT NULL DEFAULT '',\n                machine_alias TEXT NOT NULL DEFAULT '',\n                device_hidden_by_machine INTEGER NOT NULL DEFAULT 0,\n                hidden_client_ids_json TEXT NOT NULL DEFAULT '{}',\n                snapshot_json TEXT NOT NULL DEFAULT '{}'\n            )",
    SAVED_BIND_TARGETS_SCHEMA,
    'CREATE TABLE settings (\n                namespace TEXT PRIMARY KEY,\n                value_json TEXT NOT NULL,\n                updated_at_ms INTEGER NOT NULL DEFAULT 0\n            )',
    """CREATE TABLE artifact_folders (
                    folder_id TEXT PRIMARY KEY,
                    parent_id TEXT REFERENCES artifact_folders(folder_id),
                    name TEXT NOT NULL COLLATE NOCASE,
                    created_at TEXT NOT NULL
                )""",
    """CREATE TABLE artifact_entries (
                    artifact_id TEXT PRIMARY KEY,
                    artifact_type TEXT NOT NULL CHECK(artifact_type IN ('saved', 'shared', 'preview')),
                    folder_id TEXT REFERENCES artifact_folders(folder_id),
                    original_name TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    category TEXT,
                    machine_id TEXT NOT NULL DEFAULT '',
                    saved_at TEXT NOT NULL,
                    saved_path TEXT NOT NULL,
                    client_id TEXT NOT NULL DEFAULT '',
                    source_command_id TEXT,
                    extra TEXT NOT NULL DEFAULT '{}',
                    CHECK((artifact_type='saved' AND category IS NOT NULL AND folder_id IS NULL) OR
                          (artifact_type='shared' AND category IS NULL) OR
                          (artifact_type='preview' AND category IS NULL AND folder_id IS NULL))
                )""",
    """CREATE TABLE agent_outputs (
                    file_name TEXT PRIMARY KEY,
                    builder TEXT NOT NULL,
                    build_version TEXT NOT NULL,
                    connection_mode TEXT NOT NULL CHECK(connection_mode IN ('reverse', 'bind')),
                    transport TEXT NOT NULL CHECK(transport IN ('tcp', 'mtls_tcp')),
                    listener_id TEXT NOT NULL,
                    listener_name_snapshot TEXT NOT NULL,
                    target_os TEXT NOT NULL,
                    target_arch TEXT NOT NULL,
                    build_origin TEXT NOT NULL,
                    endpoint_ip TEXT NOT NULL,
                    endpoint_port INTEGER NOT NULL CHECK(endpoint_port BETWEEN 1 AND 65535),
                    web_ip TEXT NOT NULL,
                    web_port INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )""",
    'CREATE INDEX idx_artifact_folders_parent ON artifact_folders(parent_id)',
    "CREATE UNIQUE INDEX uq_artifact_folders_siblings ON artifact_folders(IFNULL(parent_id, ''), name COLLATE NOCASE)",
    'CREATE INDEX idx_artifact_entries_type_time ON artifact_entries(artifact_type, saved_at DESC, artifact_id DESC)',
    'CREATE INDEX idx_artifact_entries_folder ON artifact_entries(folder_id, saved_at DESC)',
    'CREATE INDEX idx_artifact_entries_machine ON artifact_entries(machine_id, saved_at DESC)',
    'CREATE INDEX idx_agent_outputs_created ON agent_outputs(created_at DESC, file_name DESC)',
    'CREATE INDEX idx_background_job_files_job_id ON background_job_files(job_id, association_id ASC)',
    'CREATE INDEX idx_background_job_messages_job_id ON background_job_messages(job_id, message_id ASC)',
    'CREATE INDEX idx_background_jobs_client_updated ON background_jobs(client_id, updated_at DESC, job_id DESC)',
    'CREATE INDEX idx_background_jobs_machine_state ON background_jobs(machine_id, state, updated_at DESC)',
    'CREATE INDEX idx_background_jobs_machine_updated ON background_jobs(machine_id, updated_at DESC, job_id DESC)',
    'CREATE INDEX idx_command_recents_machine_time ON command_recents(machine_id, last_used_at_ms DESC, command DESC)',
    'CREATE INDEX idx_connection_sessions_machine_time ON connection_sessions(machine_id, connected_at_ms DESC, client_id DESC)',
    'CREATE INDEX idx_external_tool_presets_tool_name ON external_tool_presets(tool_id, name COLLATE NOCASE)',
    'CREATE INDEX idx_notifications_time ON notifications(shown_at_ms DESC, id DESC)',
    'CREATE INDEX idx_pinned_commands_machine_order ON pinned_commands(machine_id, pin_order ASC)',
    'CREATE INDEX idx_pinned_paths_machine_name ON pinned_paths(machine_id, display_name COLLATE NOCASE)',
    'CREATE INDEX idx_recent_devices_last_seen ON recent_devices(last_seen_at DESC, recent_updated_at DESC)',
 ) + ADDITIONAL_SCHEMA_STATEMENTS


class RchDatabase:
    """Shared SQLite persistence for Server-managed structured runtime data."""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._local = threading.local()
        self._schema_lock = threading.RLock()
        self._savepoints = count()
        self._initialize_schema()

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 5000')
        conn.execute('PRAGMA synchronous = NORMAL')
        return conn

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, 'connection', None)
        if conn is None:
            conn = self._new_connection()
            self._local.connection = conn
        return conn

    def close_thread_connection(self):
        conn = getattr(self._local, 'connection', None)
        if conn is None:
            return
        try:
            conn.close()
        finally:
            self._local.connection = None

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        """Execute parameterized SQL on the current thread's connection."""
        return self.connection().execute(sql, params)

    def fetch_one(self, sql: str, params=()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def fetch_all(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    @contextmanager
    def transaction(self):
        """Own the outer write transaction, or a nested savepoint on the same connection.

        Nested success never commits the outer transaction. Nested failure rolls
        back only its own work and propagates the exception to the caller.
        """
        conn = self.connection()
        if getattr(self._local, 'read_snapshot', False):
            raise RuntimeError('Cannot start a write transaction inside a read snapshot')
        if conn.in_transaction:
            name = f'rch_sp_{next(self._savepoints)}'
            conn.execute(f'SAVEPOINT {name}')
            try:
                yield conn
                conn.execute(f'RELEASE SAVEPOINT {name}')
            except BaseException:
                if conn.in_transaction:
                    conn.execute(f'ROLLBACK TO SAVEPOINT {name}')
                    conn.execute(f'RELEASE SAVEPOINT {name}')
                raise
            return
        conn.execute('BEGIN IMMEDIATE')
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    @contextmanager
    def read_snapshot(self):
        """Keep related queries on one consistent SQLite snapshot without a write lock."""
        conn = self.connection()
        if conn.in_transaction:
            yield conn
            return
        previous_query_only = conn.execute('PRAGMA query_only').fetchone()[0]
        conn.execute('PRAGMA query_only = ON')
        try:
            conn.execute('BEGIN')
            self._local.read_snapshot = True
            try:
                yield conn
            finally:
                conn.rollback()
        finally:
            self._local.read_snapshot = False
            conn.execute(f'PRAGMA query_only = {int(previous_query_only)}')

    def integrity_check(self) -> str:
        row = self.connection().execute('PRAGMA integrity_check').fetchone()
        return str(row[0] if row else '')

    def space_info(self):
        conn = self.connection()
        page_size = int(conn.execute('PRAGMA page_size').fetchone()[0])
        page_count = int(conn.execute('PRAGMA page_count').fetchone()[0])
        free_pages = int(conn.execute('PRAGMA freelist_count').fetchone()[0])
        def size(path):
            try:
                return os.path.getsize(path)
            except FileNotFoundError:
                return 0
        return {'database_bytes': size(self.db_path), 'wal_bytes': size(self.db_path + '-wal'),
                'logical_bytes': page_size * page_count, 'reusable_bytes': page_size * free_pages,
                'disk_free_bytes': shutil.disk_usage(os.path.dirname(self.db_path)).free}

    def optimize_space(self):
        # VACUUM must use a standalone connection outside any transaction.
        # SQLite itself serializes writers; a busy database is reported, not forced.
        before = self.space_info()
        if before['disk_free_bytes'] < 2 * max(before['logical_bytes'], before['database_bytes'] + before['wal_bytes']):
            raise ValueError('Insufficient free disk space for database optimization')
        with closing(self._new_connection()) as conn:
            if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity check failed; optimization was not started')
            if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                raise ValueError('Database is busy; try again later')
            conn.execute('VACUUM')
            checkpoint = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database integrity check failed after optimization')
        after = self.space_info()
        return {'before': before, 'after': after, 'checkpoint_busy': bool(checkpoint[0]),
                'bytes_reclaimed': max(0, before['database_bytes'] + before['wal_bytes']
                                        - after['database_bytes'] - after['wal_bytes'])}

    def backup(self, destination_path: str):
        destination = os.path.abspath(destination_path)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        target = sqlite3.connect(destination)
        try:
            self.connection().backup(target)
        finally:
            target.close()

    @staticmethod
    def _schema_structure(conn, table_name):
        """Describe named fields and indexes, independent of physical column order."""
        quoted = '"' + table_name.replace('"', '""') + '"'
        columns = {
            row[1]: (row[2].upper(), *row[3:])
            for row in conn.execute(f'PRAGMA table_info({quoted})')
        }
        foreign_keys = tuple(tuple(row[1:]) for row in conn.execute(f'PRAGMA foreign_key_list({quoted})'))
        indexes = set()
        for index in conn.execute(f'PRAGMA index_list({quoted})'):
            index_name, unique, origin, partial = index[1:5]
            escaped_name = '"' + index_name.replace('"', '""') + '"'
            # The cid is a physical position, not part of a named index key.
            # Keep negative ids (rowid/expression) and the ordering of key terms.
            definition = tuple(
                (row[1] if row[1] < 0 else row[2], *row[2:])
                for row in conn.execute(f'PRAGMA index_xinfo({escaped_name})')
            )
            indexes.add((index_name if origin == 'c' else origin,
                         unique, origin, partial, definition))
        return columns, foreign_keys, indexes

    @classmethod
    def _schema_differences(cls, conn, reference, table_name):
        actual_columns, actual_fks, actual_indexes = cls._schema_structure(conn, table_name)
        expected_columns, expected_fks, expected_indexes = cls._schema_structure(reference, table_name)
        differences = []
        missing = expected_columns.keys() - actual_columns.keys()
        extra = actual_columns.keys() - expected_columns.keys()
        changed = {name for name in expected_columns.keys() & actual_columns.keys()
                   if expected_columns[name] != actual_columns[name]}
        for label, names in (('missing columns', missing), ('unexpected columns', extra),
                             ('changed column definitions', changed)):
            if names:
                differences.append(f'{label}: {", ".join(sorted(names))}')
        if actual_fks != expected_fks:
            differences.append('foreign key definitions differ')
        missing_indexes = expected_indexes - actual_indexes
        if missing_indexes:
            differences.append('missing or changed indexes: ' + ', '.join(
                sorted(index[0] for index in missing_indexes)))
        # Additional ordinary indexes do not change the data contract. Additional
        # unique indexes/constraints can reject otherwise valid Store writes.
        unexpected_constraints = {index for index in actual_indexes - expected_indexes if index[1]}
        if unexpected_constraints:
            differences.append('unexpected unique indexes: ' + ', '.join(
                sorted(index[0] for index in unexpected_constraints)))
        return differences

    def _initialize_schema(self):
        with self._schema_lock:
            conn = self.connection()
            conn.execute('PRAGMA journal_mode = WAL')
            with self.transaction():
                existing_tables = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if 'schema_migrations' in existing_tables:
                    raise RuntimeError(
                        'rch.db has retired schema metadata; back up and apply the standalone '
                        'SQLite schema cleanup with Server stopped before starting Server'
                    )
                if not existing_tables:
                    for statement in FINAL_SCHEMA_STATEMENTS:
                        conn.execute(statement)
                else:
                    with closing(sqlite3.connect(':memory:')) as reference:
                        for statement in FINAL_SCHEMA_STATEMENTS:
                            reference.execute(statement)
                        expected_tables = {
                            row[0] for row in reference.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                            )
                        }
                        # Add only the new business table, without rewriting existing records.
                        if 'saved_bind_targets' not in existing_tables:
                            conn.execute(SAVED_BIND_TARGETS_SCHEMA)
                            existing_tables.add('saved_bind_targets')
                        elif 'last_client_id' not in {
                            row[1] for row in conn.execute('PRAGMA table_info(saved_bind_targets)')
                        }:
                            conn.execute("ALTER TABLE saved_bind_targets ADD COLUMN last_client_id TEXT NOT NULL DEFAULT ''")
                        # Initialize the same canonical tables/indexes for all startup paths.
                        for statement in ADDITIONAL_SCHEMA_STATEMENTS:
                            conn.execute(statement)
                        existing_tables.update(row[0] for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"))
                        for table_name in sorted(expected_tables):
                            differences = (['missing table'] if table_name not in existing_tables else
                                           self._schema_differences(conn, reference, table_name))
                            if differences:
                                raise RuntimeError(
                                    f'rch.db has incompatible schema for {table_name} '
                                    f'({"; ".join(differences)}); '
                                    'back up the database and update it outside Server'
                                )
