import os
import sqlite3
import threading
from contextlib import contextmanager


# Canonical persisted schema. Database initialization never rewrites existing records.
FINAL_SCHEMA_STATEMENTS = (
    'CREATE TABLE "background_job_files" (\n                association_id INTEGER PRIMARY KEY AUTOINCREMENT,\n                job_id TEXT NOT NULL,\n                artifact_id TEXT NOT NULL,\n                created_at TEXT NOT NULL DEFAULT \'\', snapshot_json TEXT NOT NULL DEFAULT \'{}\',\n                FOREIGN KEY(job_id) REFERENCES "background_jobs"(job_id) ON DELETE CASCADE,\n                UNIQUE(job_id, artifact_id)\n            )',
    'CREATE TABLE "background_job_messages" (\n                message_id INTEGER PRIMARY KEY AUTOINCREMENT,\n                job_id TEXT NOT NULL,\n                status INTEGER NOT NULL DEFAULT 1,\n                text TEXT NOT NULL DEFAULT \'\',\n                eof INTEGER NOT NULL DEFAULT 0,\n                created_at TEXT NOT NULL DEFAULT \'\',\n                FOREIGN KEY(job_id) REFERENCES "background_jobs"(job_id) ON DELETE CASCADE\n            )',
    'CREATE TABLE "background_jobs" (\n                job_id TEXT PRIMARY KEY,\n                machine_id TEXT NOT NULL DEFAULT \'\',\n                client_id TEXT NOT NULL DEFAULT \'\',\n                hostname TEXT NOT NULL DEFAULT \'\',\n                addr TEXT NOT NULL DEFAULT \'\',\n                job_name TEXT NOT NULL DEFAULT \'\',\n                job_key TEXT NOT NULL DEFAULT \'\',\n                thread_name TEXT NOT NULL DEFAULT \'\',\n                command_id INTEGER,\n                execution_mode TEXT NOT NULL DEFAULT \'inproc\',\n                state TEXT NOT NULL DEFAULT \'unknown\',\n                created_at TEXT NOT NULL DEFAULT \'\',\n                started_at TEXT NOT NULL DEFAULT \'\',\n                updated_at TEXT NOT NULL DEFAULT \'\',\n                finished_at TEXT NOT NULL DEFAULT \'\',\n                params_json TEXT NOT NULL DEFAULT \'{}\'\n            )',
    'CREATE TABLE "command_executions" (\n                entry_id TEXT PRIMARY KEY,\n                machine_id TEXT NOT NULL,\n                client_id TEXT NOT NULL DEFAULT \'\',\n                hostname TEXT NOT NULL DEFAULT \'\',\n                addr TEXT NOT NULL DEFAULT \'\',\n                command TEXT NOT NULL,\n                raw_command TEXT NOT NULL DEFAULT \'\',\n                source TEXT NOT NULL DEFAULT \'\',\n                status TEXT NOT NULL DEFAULT \'\',\n                created_at TEXT NOT NULL DEFAULT \'\',\n                started_at TEXT NOT NULL DEFAULT \'\',\n                started_at_ms INTEGER NOT NULL DEFAULT 0,\n                updated_at TEXT NOT NULL DEFAULT \'\',\n                finished_at TEXT NOT NULL DEFAULT \'\',\n                cwd_start TEXT NOT NULL DEFAULT \'\',\n                cwd_end TEXT NOT NULL DEFAULT \'\',\n                output_line_count INTEGER NOT NULL DEFAULT 0,\n                output_chunk_count INTEGER NOT NULL DEFAULT 0,\n                output_char_count INTEGER NOT NULL DEFAULT 0,\n                output_truncated INTEGER NOT NULL DEFAULT 0,\n                output_records_json TEXT NOT NULL DEFAULT \'[]\',\n                files_json TEXT NOT NULL DEFAULT \'[]\'\n            )',
    "CREATE TABLE command_recents (\n                machine_id TEXT NOT NULL,\n                command TEXT NOT NULL,\n                last_used_at TEXT NOT NULL DEFAULT '',\n                last_used_at_ms INTEGER NOT NULL DEFAULT 0,\n                use_count INTEGER NOT NULL DEFAULT 1,\n                snapshot_json TEXT NOT NULL DEFAULT '{}',\n                PRIMARY KEY(machine_id, command)\n            )",
    "CREATE TABLE connection_sessions (\n                machine_id TEXT NOT NULL,\n                client_id TEXT NOT NULL,\n                connected_at TEXT NOT NULL DEFAULT '',\n                connected_at_ms INTEGER NOT NULL DEFAULT 0,\n                disconnected_at TEXT NOT NULL DEFAULT '',\n                disconnected_at_ms INTEGER NOT NULL DEFAULT 0,\n                last_seen_at TEXT NOT NULL DEFAULT '',\n                duration_ms INTEGER NOT NULL DEFAULT 0,\n                connection_state TEXT NOT NULL DEFAULT '',\n                termination_reason TEXT NOT NULL DEFAULT '',\n                termination_detail_json TEXT NOT NULL DEFAULT '{}',\n                tracking_source TEXT NOT NULL DEFAULT 'connection_lifecycle',\n                snapshot_json TEXT NOT NULL DEFAULT '{}',\n                PRIMARY KEY(machine_id, client_id)\n            )",
    'CREATE TABLE device_group_members (\n                machine_id TEXT PRIMARY KEY,\n                group_id TEXT NOT NULL,\n                FOREIGN KEY(group_id) REFERENCES device_groups(group_id) ON DELETE CASCADE\n            )',
    "CREATE TABLE device_groups (\n                group_id TEXT PRIMARY KEY,\n                name TEXT NOT NULL COLLATE NOCASE UNIQUE,\n                created_at TEXT NOT NULL DEFAULT '',\n                updated_at TEXT NOT NULL DEFAULT ''\n            )",
    "CREATE TABLE external_tool_presets (\n                preset_id TEXT PRIMARY KEY,\n                tool_id TEXT NOT NULL,\n                name TEXT NOT NULL COLLATE NOCASE,\n                params_json TEXT NOT NULL DEFAULT '{}',\n                created_at TEXT NOT NULL DEFAULT '',\n                updated_at TEXT NOT NULL DEFAULT '',\n                UNIQUE(tool_id, name)\n            )",
    "CREATE TABLE notifications (\n                id TEXT PRIMARY KEY,\n                event_id TEXT UNIQUE,\n                notification_key TEXT NOT NULL DEFAULT '',\n                type TEXT NOT NULL DEFAULT 'info',\n                title TEXT NOT NULL,\n                message TEXT NOT NULL DEFAULT '',\n                shown_at TEXT NOT NULL DEFAULT '',\n                shown_at_ms INTEGER NOT NULL DEFAULT 0,\n                context_json TEXT NOT NULL DEFAULT '{}',\n                actions_json TEXT NOT NULL DEFAULT '[]'\n            )",
    "CREATE TABLE pinned_commands (\n                machine_id TEXT NOT NULL,\n                command TEXT NOT NULL,\n                pinned_at TEXT NOT NULL,\n                pin_order INTEGER NOT NULL DEFAULT 0,\n                snapshot_json TEXT NOT NULL DEFAULT '{}',\n                PRIMARY KEY(machine_id, command)\n            )",
    "CREATE TABLE pinned_paths (\n                machine_id TEXT NOT NULL,\n                display_name TEXT NOT NULL,\n                path TEXT NOT NULL,\n                created_at TEXT NOT NULL DEFAULT '',\n                updated_at TEXT NOT NULL DEFAULT '',\n                PRIMARY KEY(machine_id, display_name)\n            )",
    "CREATE TABLE recent_devices (\n                machine_key TEXT PRIMARY KEY,\n                machine_id TEXT NOT NULL,\n                client_id TEXT NOT NULL DEFAULT '',\n                machine_order INTEGER NOT NULL DEFAULT 0,\n                connection_state TEXT NOT NULL DEFAULT 'offline',\n                last_seen_at TEXT NOT NULL DEFAULT '',\n                recent_updated_at TEXT NOT NULL DEFAULT '',\n                machine_alias TEXT NOT NULL DEFAULT '',\n                device_hidden_by_machine INTEGER NOT NULL DEFAULT 0,\n                hidden_client_ids_json TEXT NOT NULL DEFAULT '{}',\n                snapshot_json TEXT NOT NULL DEFAULT '{}'\n            )",
    'CREATE TABLE settings (\n                namespace TEXT PRIMARY KEY,\n                value_json TEXT NOT NULL,\n                updated_at_ms INTEGER NOT NULL DEFAULT 0\n            )',
    'CREATE INDEX idx_background_job_files_job_id ON background_job_files(job_id, association_id ASC)',
    'CREATE INDEX idx_background_job_messages_job_id ON background_job_messages(job_id, message_id ASC)',
    'CREATE INDEX idx_background_jobs_client_updated ON background_jobs(client_id, updated_at DESC, job_id DESC)',
    'CREATE INDEX idx_background_jobs_machine_state ON background_jobs(machine_id, state, updated_at DESC)',
    'CREATE INDEX idx_background_jobs_machine_updated ON background_jobs(machine_id, updated_at DESC, job_id DESC)',
    'CREATE INDEX idx_command_executions_client_time ON command_executions(machine_id, client_id, started_at_ms DESC)',
    'CREATE INDEX idx_command_executions_machine_command ON command_executions(machine_id, command, started_at_ms DESC)',
    'CREATE INDEX idx_command_executions_machine_status ON command_executions(machine_id, status, started_at_ms DESC)',
    'CREATE INDEX idx_command_executions_machine_time ON command_executions(machine_id, started_at_ms DESC, entry_id DESC)',
    'CREATE INDEX idx_command_recents_machine_time ON command_recents(machine_id, last_used_at_ms DESC, command DESC)',
    'CREATE INDEX idx_connection_sessions_machine_time ON connection_sessions(machine_id, connected_at_ms DESC, client_id DESC)',
    'CREATE INDEX idx_external_tool_presets_tool_name ON external_tool_presets(tool_id, name COLLATE NOCASE)',
    'CREATE INDEX idx_notifications_time ON notifications(shown_at_ms DESC, id DESC)',
    'CREATE INDEX idx_pinned_commands_machine_order ON pinned_commands(machine_id, pin_order ASC)',
    'CREATE INDEX idx_pinned_paths_machine_name ON pinned_paths(machine_id, display_name COLLATE NOCASE)',
    'CREATE INDEX idx_recent_devices_last_seen ON recent_devices(last_seen_at DESC, recent_updated_at DESC)',
 )


class RchDatabase:
    """Shared SQLite persistence for Server-managed structured runtime data."""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._local = threading.local()
        self._schema_lock = threading.RLock()
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

    @contextmanager
    def transaction(self):
        conn = self.connection()
        conn.execute('BEGIN IMMEDIATE')
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()

    def integrity_check(self) -> str:
        row = self.connection().execute('PRAGMA integrity_check').fetchone()
        return str(row[0] if row else '')

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
        """Compare durable columns, foreign keys and indexes, without SQL formatting noise."""
        quoted = '"' + table_name.replace('"', '""') + '"'
        columns = tuple(tuple(row[1:]) for row in conn.execute(f'PRAGMA table_info({quoted})'))
        foreign_keys = tuple(tuple(row[1:]) for row in conn.execute(f'PRAGMA foreign_key_list({quoted})'))
        indexes = []
        for index in conn.execute(f'PRAGMA index_list({quoted})'):
            index_name, unique, origin, partial = index[1:5]
            escaped_name = '"' + index_name.replace('"', '""') + '"'
            definition = tuple(tuple(row[1:]) for row in conn.execute(f'PRAGMA index_xinfo({escaped_name})'))
            indexes.append((index_name if origin == 'c' else origin,
                            unique, origin, partial, definition))
        return columns, foreign_keys, tuple(sorted(indexes, key=str))

    def _initialize_schema(self):
        with self._schema_lock:
            conn = self.connection()
            conn.execute('PRAGMA journal_mode = WAL')
            conn.execute('BEGIN IMMEDIATE')
            try:
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
                    with sqlite3.connect(':memory:') as reference:
                        for statement in FINAL_SCHEMA_STATEMENTS:
                            reference.execute(statement)
                        expected_tables = {
                            row[0] for row in reference.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                            )
                        }
                        for table_name in expected_tables:
                            if table_name not in existing_tables or (
                                self._schema_structure(conn, table_name) !=
                                self._schema_structure(reference, table_name)
                            ):
                                raise RuntimeError(
                                    f'rch.db has incompatible schema for {table_name}; '
                                    'back up the database and update it outside Server'
                                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
