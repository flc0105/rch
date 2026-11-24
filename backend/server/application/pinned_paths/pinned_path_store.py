from datetime import datetime


class PinnedPathStore:
    """SQLite-backed machine-level Remote Files pinned paths."""

    TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _normalize_machine_id(machine_id: str) -> str:
        return str(machine_id or '').strip() or 'unknown_machine'

    def _now_text(self) -> str:
        return datetime.now().strftime(self.TIME_FORMAT)

    @staticmethod
    def _row_to_item(row) -> dict:
        return {
            'display_name': row['display_name'],
            'path': row['path'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        }

    def list_items(self, machine_id: str) -> list[dict]:
        machine_id_text = self._normalize_machine_id(machine_id)
        rows = self.database.fetch_all(
            '''
            SELECT display_name, path, created_at, updated_at
            FROM pinned_paths
            WHERE machine_id = ?
            ORDER BY display_name COLLATE NOCASE ASC
            ''',
            (machine_id_text,),
        )
        return [self._row_to_item(row) for row in rows]

    def save_item(self, machine_id: str, display_name: str, path: str) -> dict:
        machine_id_text = self._normalize_machine_id(machine_id)
        display_name_text = str(display_name or '').strip()
        path_text = str(path or '').strip()
        if not display_name_text:
            raise ValueError('display_name is required')
        if not path_text:
            raise ValueError('path is required')

        with self.database.transaction() as conn:
            row = conn.execute(
                'SELECT created_at FROM pinned_paths WHERE machine_id = ? AND display_name = ?',
                (machine_id_text, display_name_text),
            ).fetchone()
            now_text = self._now_text()
            created_at = row['created_at'] if row else now_text
            conn.execute(
                '''
                INSERT INTO pinned_paths(machine_id, display_name, path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(machine_id, display_name) DO UPDATE SET
                    path = excluded.path,
                    updated_at = excluded.updated_at
                ''',
                (machine_id_text, display_name_text, path_text, created_at, now_text),
            )
            return {
                'display_name': display_name_text,
                'path': path_text,
                'created_at': created_at,
                'updated_at': now_text,
            }

    def update_item(self, machine_id: str, original_display_name: str, display_name: str, path: str) -> dict:
        machine_id_text = self._normalize_machine_id(machine_id)
        original_name = str(original_display_name or '').strip()
        display_name_text = str(display_name or '').strip()
        path_text = str(path or '').strip()
        if not original_name:
            raise ValueError('original_display_name is required')
        if not display_name_text:
            raise ValueError('display_name is required')
        if not path_text:
            raise ValueError('path is required')

        with self.database.transaction() as conn:
            current = conn.execute(
                'SELECT * FROM pinned_paths WHERE machine_id = ? AND display_name = ?',
                (machine_id_text, original_name),
            ).fetchone()
            if current is None:
                raise KeyError(f'Pinned path not found: {original_name}')
            if display_name_text != original_name:
                duplicate = conn.execute(
                    'SELECT 1 FROM pinned_paths WHERE machine_id = ? AND display_name = ?',
                    (machine_id_text, display_name_text),
                ).fetchone()
                if duplicate is not None:
                    raise ValueError(f'Pinned path already exists: {display_name_text}')

            now_text = self._now_text()
            conn.execute(
                '''UPDATE pinned_paths SET display_name = ?, path = ?, updated_at = ?
                   WHERE machine_id = ? AND display_name = ?''',
                (display_name_text, path_text, now_text, machine_id_text, original_name),
            )
            return {
                'display_name': display_name_text,
                'path': path_text,
                'created_at': current['created_at'],
                'updated_at': now_text,
            }

    def delete_item(self, machine_id: str, display_name: str) -> dict:
        machine_id_text = self._normalize_machine_id(machine_id)
        display_name_text = str(display_name or '').strip()
        if not display_name_text:
            raise ValueError('display_name is required')

        with self.database.transaction() as conn:
            row = conn.execute(
                'SELECT * FROM pinned_paths WHERE machine_id = ? AND display_name = ?',
                (machine_id_text, display_name_text),
            ).fetchone()
            if row is None:
                raise KeyError(f'Pinned path not found: {display_name_text}')
            conn.execute(
                'DELETE FROM pinned_paths WHERE machine_id = ? AND display_name = ?',
                (machine_id_text, display_name_text),
            )
            return self._row_to_item(row)

    def get_item_by_name(self, machine_id: str, display_name: str) -> dict | None:
        machine_id_text = self._normalize_machine_id(machine_id)
        display_name_text = str(display_name or '').strip()
        if not display_name_text:
            return None
        row = self.database.fetch_one(
            'SELECT * FROM pinned_paths WHERE machine_id = ? AND display_name = ?',
            (machine_id_text, display_name_text),
        )
        return self._row_to_item(row) if row is not None else None
