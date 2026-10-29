#!/usr/bin/env python3
"""Standalone RCH SQLite connection-history column migration.

Stop the RCH Server before running this script. The Server and its clients must
not write the database during migration.

From the project root:
    python backend/tools/migrate_connection_session_columns.py --db backend/runtime/rch.db

If RCH_SERVER_RUNTIME_DIR is configured, pass the matching rch.db using --db.
The script creates a verified SQLite backup next to the source database before
changing its connection_sessions columns. The backup filename is printed.

Supports earlier reason/detail_json columns, termination_reason/error_diagnostics_json,
older installations without those columns, and databases already using canonical names.
Uses Python's standard sqlite3 module; no project imports or Server startup.
"""

import argparse
import os
import secrets
import sqlite3
import sys
from datetime import datetime
from contextlib import closing
from pathlib import Path


COLUMN_SPECS = (
    ('termination_reason', ('reason',), "TEXT NOT NULL DEFAULT ''"),
    ('termination_detail_json', ('error_diagnostics_json', 'detail_json'), "TEXT NOT NULL DEFAULT '{}'"),
)


ABNORMAL_REASONS = (
    'connection_lost', 'transport_error', 'timeout', 'unexpected_disconnect', 'client_error',
)


def count_previous_abnormal_rows(connection):
    columns = table_columns(connection)
    if 'termination_reason' not in columns:
        return 0
    conditions = ', '.join('?' for _ in ABNORMAL_REASONS)
    return connection.execute(
        f"SELECT COUNT(*) FROM connection_sessions WHERE disconnected_at != '' "
        f"AND termination_reason IN ({conditions}) "
        "AND connection_state != 'interrupted'",
        ABNORMAL_REASONS,
    ).fetchone()[0]


def normalize_abnormal_states(connection):
    conditions = ', '.join('?' for _ in ABNORMAL_REASONS)
    cursor = connection.execute(
        f"UPDATE connection_sessions SET connection_state = 'interrupted' WHERE disconnected_at != '' "
        f"AND termination_reason IN ({conditions}) "
        "AND connection_state != 'interrupted'",
        ABNORMAL_REASONS,
    )
    return cursor.rowcount


def table_columns(connection):
    table = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = 'connection_sessions'"
    ).fetchone()
    if table is None or table[0] != 'table':
        raise RuntimeError('Required table connection_sessions was not found')
    return {item[1] for item in connection.execute('PRAGMA table_info(connection_sessions)')}


def migration_plan(columns):
    """Generate a single canonical column layout and track any renamed source."""
    operations = []
    sources = {}
    for target, old_names, declaration in COLUMN_SPECS:
        present = [name for name in (*old_names, target) if name in columns]
        if len(present) > 1:
            raise RuntimeError(
                f'Conflicting columns for {target}: {", ".join(present)}; '
                'resolve the conflicting data before migration'
            )
        if present and present[0] == target:
            continue
        if present:
            source = present[0]
            sources[source] = target
            operations.append(f'ALTER TABLE connection_sessions RENAME COLUMN {source} TO {target}')
        else:
            operations.append(f'ALTER TABLE connection_sessions ADD COLUMN {target} {declaration}')
    return operations, sources


def verify_integrity(connection, label):
    check = connection.execute('PRAGMA integrity_check').fetchone()
    if check is None or check[0] != 'ok':
        raise RuntimeError(f'{label} failed SQLite integrity_check: {check}')


def next_backup_path(database_path):
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return database_path.with_name(
        f'{database_path.name}.before-termination-columns-{timestamp}-{secrets.token_hex(4)}.bak'
    )


def create_backup(connection, database_path):
    """Capture a consistent backup, including committed WAL transactions."""
    backup_path = next_backup_path(database_path)
    fd = os.open(str(backup_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(str(backup_path))) as backup:
            connection.backup(backup)
            verify_integrity(backup, 'Backup')
        return backup_path
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise


def verify_preserved_data(original_backup, migrated_connection, source_columns, original_count):
    """Compare every renamed value against the verified snapshot."""
    row_count = migrated_connection.execute(
        'SELECT COUNT(*) FROM connection_sessions'
    ).fetchone()[0]
    if row_count != original_count:
        raise RuntimeError('Connection session row count changed during migration')

    with closing(sqlite3.connect(str(original_backup))) as backup:
        verify_integrity(backup, 'Backup')
        backup_count = backup.execute('SELECT COUNT(*) FROM connection_sessions').fetchone()[0]
        if backup_count != row_count:
            raise RuntimeError('Connection session count differs from verified backup')
        for source, target in source_columns.items():
            originals = list(backup.execute(
                f'SELECT machine_id, client_id, {source} FROM connection_sessions '
                'ORDER BY machine_id, client_id'
            ))
            migrated = list(migrated_connection.execute(
                f'SELECT machine_id, client_id, {target} FROM connection_sessions '
                'ORDER BY machine_id, client_id'
            ))
            if originals != migrated:
                raise RuntimeError(f'Preserved data verification failed for {target}')


def migrate(database_path, dry_run=False):
    if not database_path.is_file():
        raise FileNotFoundError(f'Database file not found: {database_path}')
    if sqlite3.sqlite_version_info < (3, 25, 0):
        raise RuntimeError('SQLite 3.25.0 or newer is required for RENAME COLUMN')

    # mode=rw prevents sqlite3 from creating a new, empty database on typo.
    uri = database_path.resolve().as_uri() + '?mode=rw'
    with closing(sqlite3.connect(uri, uri=True, timeout=3.0)) as connection:
        connection.execute('PRAGMA busy_timeout = 3000')
        verify_integrity(connection, 'Original database')
        initial_columns = table_columns(connection)
        operations, sources = migration_plan(initial_columns)
        count = connection.execute('SELECT COUNT(*) FROM connection_sessions').fetchone()[0]
        print(f'Database: {database_path.resolve()}')
        print(f'Connection history rows: {count}')
        needs_state_update = count_previous_abnormal_rows(connection)
        # Older schemas may rename 'reason' during the same transaction.
        if 'termination_reason' not in initial_columns and 'reason' in initial_columns:
            needs_state_update = connection.execute(
                "SELECT COUNT(*) FROM connection_sessions WHERE disconnected_at != '' "
                "AND reason IN ('connection_lost', 'transport_error', 'timeout', 'unexpected_disconnect', 'client_error') "
                "AND connection_state != 'interrupted'"
            ).fetchone()[0]
        print(f'Prior abnormal sessions to update: {needs_state_update}')
        if not operations and not needs_state_update:
            print('Canonical columns and session states are already up to date.')
            return None
        for statement in operations:
            print(f'  {statement};')
        if dry_run:
            print('Dry run complete; no backup or database changes made.')
            return None

        backup_path = create_backup(connection, database_path)
        print(f'Backup: {backup_path}')
        try:
            connection.execute('BEGIN IMMEDIATE')
            # Another process must not alter the table after inspection.
            if table_columns(connection) != initial_columns:
                raise RuntimeError('Table columns changed since inspection')
            for statement in operations:
                connection.execute(statement)
            columns = table_columns(connection)
            for target, old_names, _ in COLUMN_SPECS:
                if target not in columns or any(old in columns for old in old_names):
                    raise RuntimeError(f'Migration did not fully normalize {target}')
            normalized = normalize_abnormal_states(connection)
            print(f'Updated abnormal session states: {normalized}')
            verify_integrity(connection, 'Migrated database')
            verify_preserved_data(backup_path, connection, sources, count)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        verify_integrity(connection, 'Committed database')
        print('Migration complete: connection_sessions now uses '
              'termination_reason and termination_detail_json.')
        print('All existing tables, session records and detail payloads are preserved.')
        return backup_path


def main(argv=None):
    default_path = Path(__file__).resolve().parent.parent / 'runtime' / 'rch.db'
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', type=Path, default=default_path, help='Path to the existing Server runtime/rch.db')
    parser.add_argument('--dry-run', action='store_true', help='Show planned SQL without modifying the database')
    args = parser.parse_args(argv)
    try:
        migrate(args.db, args.dry_run)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        print('Stop the RCH Server; keep the existing database and its backup unchanged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
