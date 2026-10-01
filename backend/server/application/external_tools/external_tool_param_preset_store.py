import sqlite3
import threading
import uuid
from datetime import datetime


from core.utils.json_utils import clone_json_value, compact_json_dumps, json_loads_dict
class ExternalToolParamPresetStore:
    """External Tool parameter presets stored in shared rch.db."""

    TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()

    def _now_text(self) -> str:
        return datetime.now().strftime(self.TIME_FORMAT)

    @staticmethod
    def _normalize_tool_id(tool_id: str) -> str:
        value = str(tool_id or '').strip()
        if not value:
            raise ValueError('tool_id is required')
        return value

    @staticmethod
    def _copy_params(params) -> dict:
        if not isinstance(params, dict):
            raise ValueError('params must be an object')
        try:
            return clone_json_value(params)
        except Exception as exc:
            raise ValueError(f'params must be JSON serializable: {exc}') from exc

    def _row_to_item(self, row) -> dict:
        return {
            'preset_id': row['preset_id'],
            'name': row['name'],
            'params': json_loads_dict(row['params_json']),
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        }

    def _assert_unique_name(self, conn, tool_id: str, name: str, *, exclude_preset_id: str = ''):
        target = str(name or '').strip().lower()
        rows = conn.execute(
            'SELECT preset_id, name FROM external_tool_presets WHERE tool_id = ?',
            (tool_id,),
        ).fetchall()
        for row in rows:
            if exclude_preset_id and str(row['preset_id'] or '') == exclude_preset_id:
                continue
            if str(row['name'] or '').strip().lower() == target:
                raise ValueError(f'Preset already exists: {name}')

    def list_presets(self, tool_id: str) -> list[dict]:
        tool_id_text = self._normalize_tool_id(tool_id)
        with self._lock:
            rows = self.database.connection().execute(
                '''SELECT * FROM external_tool_presets WHERE tool_id = ? ORDER BY name COLLATE NOCASE ASC''',
                (tool_id_text,),
            ).fetchall()
            return [self._row_to_item(row) for row in rows]

    def create_preset(self, tool_id: str, name: str, params: dict) -> dict:
        tool_id_text = self._normalize_tool_id(tool_id)
        name_text = str(name or '').strip()
        if not name_text:
            raise ValueError('preset name is required')
        params_copy = self._copy_params(params)
        now_text = self._now_text()
        item = {
            'preset_id': uuid.uuid4().hex,
            'name': name_text,
            'params': params_copy,
            'created_at': now_text,
            'updated_at': now_text,
        }
        with self._lock:
            conn = self.database.connection()
            self._assert_unique_name(conn, tool_id_text, name_text)
            try:
                conn.execute(
                    '''INSERT INTO external_tool_presets(preset_id, tool_id, name, params_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (
                        item['preset_id'], tool_id_text, name_text, compact_json_dumps(params_copy),
                        now_text, now_text,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f'Preset already exists: {name_text}') from exc
        return item

    def update_preset(self, tool_id: str, preset_id: str, *, name: str = '', params=None) -> dict:
        tool_id_text = self._normalize_tool_id(tool_id)
        preset_id_text = str(preset_id or '').strip()
        if not preset_id_text:
            raise ValueError('preset_id is required')

        with self._lock, self.database.transaction() as conn:
            row = conn.execute(
                'SELECT * FROM external_tool_presets WHERE tool_id = ? AND preset_id = ?',
                (tool_id_text, preset_id_text),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f'Preset not found: {preset_id_text}')

            name_text = str(name).strip() if name else row['name']
            if not name_text:
                raise ValueError('preset name is required')
            params_copy = self._copy_params(params) if params is not None else json_loads_dict(row['params_json'])
            self._assert_unique_name(conn, tool_id_text, name_text, exclude_preset_id=preset_id_text)
            updated_at = self._now_text()
            try:
                conn.execute(
                    '''UPDATE external_tool_presets SET name = ?, params_json = ?, updated_at = ?
                       WHERE tool_id = ? AND preset_id = ?''',
                    (name_text, compact_json_dumps(params_copy), updated_at, tool_id_text, preset_id_text),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f'Preset already exists: {name_text}') from exc
            return {
                'preset_id': preset_id_text,
                'name': name_text,
                'params': params_copy,
                'created_at': row['created_at'],
                'updated_at': updated_at,
            }

    def delete_preset(self, tool_id: str, preset_id: str) -> dict:
        tool_id_text = self._normalize_tool_id(tool_id)
        preset_id_text = str(preset_id or '').strip()
        if not preset_id_text:
            raise ValueError('preset_id is required')

        with self._lock, self.database.transaction() as conn:
            row = conn.execute(
                'SELECT * FROM external_tool_presets WHERE tool_id = ? AND preset_id = ?',
                (tool_id_text, preset_id_text),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f'Preset not found: {preset_id_text}')
            conn.execute(
                'DELETE FROM external_tool_presets WHERE tool_id = ? AND preset_id = ?',
                (tool_id_text, preset_id_text),
            )
            return self._row_to_item(row)
