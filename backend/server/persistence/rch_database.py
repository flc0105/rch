import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime


class RchDatabase:
    """Shared SQLite persistence for Server-managed structured runtime data."""

    SCHEMA_VERSION = 2

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

    def _initialize_schema(self):
        with self._schema_lock:
            conn = self.connection()
            conn.execute('PRAGMA journal_mode = WAL')
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    '''
                )
                row = conn.execute('SELECT COALESCE(MAX(version), 0) FROM schema_migrations').fetchone()
                current_version = int(row[0] if row else 0)
                if current_version > self.SCHEMA_VERSION:
                    raise RuntimeError(
                        f'rch.db schema version {current_version} is newer than supported {self.SCHEMA_VERSION}'
                    )
                if current_version < 1:
                    self._apply_schema_v1(conn)
                    conn.execute(
                        'INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)',
                        (1, datetime.now().isoformat()),
                    )
                    current_version = 1
                if current_version < 2:
                    self._apply_schema_v2(conn)
                    conn.execute(
                        'INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)',
                        (2, datetime.now().isoformat()),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _apply_schema_v1(conn: sqlite3.Connection):
        statements = [
            '''
            CREATE TABLE command_executions (
                entry_id TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                client_id TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                addr TEXT NOT NULL DEFAULT '',
                command TEXT NOT NULL,
                raw_command TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                final_status TEXT NOT NULL DEFAULT '',
                time_text TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                started_at_ms INTEGER NOT NULL DEFAULT 0,
                finished_at TEXT NOT NULL DEFAULT '',
                finished_at_ms INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                cwd_start TEXT NOT NULL DEFAULT '',
                cwd_end TEXT NOT NULL DEFAULT '',
                has_output INTEGER NOT NULL DEFAULT 0,
                output_summary TEXT NOT NULL DEFAULT '',
                output_line_count INTEGER NOT NULL DEFAULT 0,
                output_chunk_count INTEGER NOT NULL DEFAULT 0,
                output_char_count INTEGER NOT NULL DEFAULT 0,
                output_stored_char_count INTEGER NOT NULL DEFAULT 0,
                output_truncated INTEGER NOT NULL DEFAULT 0,
                output_record_seq INTEGER NOT NULL DEFAULT 0,
                output_records_json TEXT NOT NULL DEFAULT '[]',
                has_files INTEGER NOT NULL DEFAULT 0,
                file_count INTEGER NOT NULL DEFAULT 0,
                files_json TEXT NOT NULL DEFAULT '[]'
            )
            ''',
            'CREATE INDEX idx_command_executions_machine_time ON command_executions(machine_id, started_at_ms DESC, entry_id DESC)',
            'CREATE INDEX idx_command_executions_machine_command ON command_executions(machine_id, command, started_at_ms DESC)',
            'CREATE INDEX idx_command_executions_machine_status ON command_executions(machine_id, status, started_at_ms DESC)',
            'CREATE INDEX idx_command_executions_client_time ON command_executions(machine_id, client_id, started_at_ms DESC)',
            '''
            CREATE TABLE command_recents (
                machine_id TEXT NOT NULL,
                command TEXT NOT NULL,
                last_entry_id TEXT NOT NULL DEFAULT '',
                last_used_at TEXT NOT NULL DEFAULT '',
                last_used_at_ms INTEGER NOT NULL DEFAULT 0,
                use_count INTEGER NOT NULL DEFAULT 1,
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(machine_id, command)
            )
            ''',
            'CREATE INDEX idx_command_recents_machine_time ON command_recents(machine_id, last_used_at_ms DESC, command DESC)',
            '''
            CREATE TABLE pinned_commands (
                machine_id TEXT NOT NULL,
                command TEXT NOT NULL,
                pinned_at TEXT NOT NULL,
                pin_order INTEGER NOT NULL DEFAULT 0,
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(machine_id, command)
            )
            ''',
            'CREATE INDEX idx_pinned_commands_machine_order ON pinned_commands(machine_id, pin_order ASC)',
            '''
            CREATE TABLE connection_sessions (
                machine_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                connected_at TEXT NOT NULL DEFAULT '',
                connected_at_ms INTEGER NOT NULL DEFAULT 0,
                disconnected_at TEXT NOT NULL DEFAULT '',
                disconnected_at_ms INTEGER NOT NULL DEFAULT 0,
                last_seen_at TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                connection_state TEXT NOT NULL DEFAULT '',
                disconnect_reason TEXT NOT NULL DEFAULT '',
                tracking_source TEXT NOT NULL DEFAULT 'connection_lifecycle',
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(machine_id, client_id)
            )
            ''',
            'CREATE INDEX idx_connection_sessions_machine_time ON connection_sessions(machine_id, connected_at_ms DESC, client_id DESC)',
            '''
            CREATE TABLE recent_devices (
                machine_key TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                client_id TEXT NOT NULL DEFAULT '',
                machine_order INTEGER NOT NULL DEFAULT 0,
                connection_state TEXT NOT NULL DEFAULT 'offline',
                last_seen_at TEXT NOT NULL DEFAULT '',
                recent_updated_at TEXT NOT NULL DEFAULT '',
                machine_alias TEXT NOT NULL DEFAULT '',
                device_hidden_by_machine INTEGER NOT NULL DEFAULT 0,
                hidden_client_ids_json TEXT NOT NULL DEFAULT '{}',
                snapshot_json TEXT NOT NULL DEFAULT '{}'
            )
            ''',
            'CREATE INDEX idx_recent_devices_last_seen ON recent_devices(last_seen_at DESC, recent_updated_at DESC)',
            '''
            CREATE TABLE device_groups (
                group_id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            ''',
            '''
            CREATE TABLE device_group_members (
                machine_id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                FOREIGN KEY(group_id) REFERENCES device_groups(group_id) ON DELETE CASCADE
            )
            ''',
            '''
            CREATE TABLE pinned_paths (
                machine_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(machine_id, display_name)
            )
            ''',
            'CREATE INDEX idx_pinned_paths_machine_name ON pinned_paths(machine_id, display_name COLLATE NOCASE)',
            '''
            CREATE TABLE notifications (
                id TEXT PRIMARY KEY,
                event_id TEXT UNIQUE,
                notification_key TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                shown_at TEXT NOT NULL DEFAULT '',
                shown_at_ms INTEGER NOT NULL DEFAULT 0,
                context_json TEXT NOT NULL DEFAULT '{}',
                actions_json TEXT NOT NULL DEFAULT '[]'
            )
            ''',
            'CREATE INDEX idx_notifications_time ON notifications(shown_at_ms DESC, id DESC)',
            '''
            CREATE TABLE settings (
                namespace TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL DEFAULT 0
            )
            ''',
            '''
            CREATE TABLE external_tool_presets (
                preset_id TEXT PRIMARY KEY,
                tool_id TEXT NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                params_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                UNIQUE(tool_id, name)
            )
            ''',
            'CREATE INDEX idx_external_tool_presets_tool_name ON external_tool_presets(tool_id, name COLLATE NOCASE)',
        ]
        for statement in statements:
            conn.execute(statement)

    @staticmethod
    def _apply_schema_v2(conn: sqlite3.Connection):
        statements = [
            '''
            CREATE TABLE background_jobs (
                job_id TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL DEFAULT '',
                client_id TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                job_name TEXT NOT NULL DEFAULT '',
                job_key TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                thread_name TEXT NOT NULL DEFAULT '',
                command_id INTEGER,
                execution_mode TEXT NOT NULL DEFAULT 'inproc',
                state TEXT NOT NULL DEFAULT 'unknown',
                created_at TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                stopped_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                last_message TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                file_count INTEGER NOT NULL DEFAULT 0,
                params_json TEXT NOT NULL DEFAULT '{}'
            )
            ''',
            'CREATE INDEX idx_background_jobs_machine_updated ON background_jobs(machine_id, updated_at DESC, job_id DESC)',
            'CREATE INDEX idx_background_jobs_machine_state ON background_jobs(machine_id, state, updated_at DESC)',
            'CREATE INDEX idx_background_jobs_client_updated ON background_jobs(client_id, updated_at DESC, job_id DESC)',
            '''
            CREATE TABLE background_job_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                status INTEGER NOT NULL DEFAULT 1,
                text TEXT NOT NULL DEFAULT '',
                eof INTEGER NOT NULL DEFAULT 0,
                event_time TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(job_id) REFERENCES background_jobs(job_id) ON DELETE CASCADE
            )
            ''',
            'CREATE INDEX idx_background_job_messages_job_id ON background_job_messages(job_id, message_id ASC)',
            '''
            CREATE TABLE background_job_files (
                association_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                event_time TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(job_id) REFERENCES background_jobs(job_id) ON DELETE CASCADE,
                UNIQUE(job_id, artifact_id)
            )
            ''',
            'CREATE INDEX idx_background_job_files_job_id ON background_job_files(job_id, association_id ASC)',
        ]
        for statement in statements:
            conn.execute(statement)
