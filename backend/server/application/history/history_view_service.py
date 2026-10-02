import base64
import json
from server.application.artifact.artifact_reference_view_projector import ArtifactReferenceViewProjector
from server.config.config import COMMAND_HISTORY_MAX_PAGE_SIZE, COMMAND_HISTORY_PAGE_SIZE


class HistoryViewService:
    """Command history read models: Quick History and paged permanent executions."""

    def __init__(self, store):
        self.store = store
        self.artifact_view_projector = ArtifactReferenceViewProjector()

    def _resolve_artifact_file_view(self, file_item: dict) -> dict:
        return self.artifact_view_projector.project(
            file_item,
            self.store.artifact_service,
            path_key='saved_path',
            allow_local_path_fallback=True,
            include_created_at=True,
        )

    def _refresh_file_status_for_view(self, item: dict) -> dict:
        copied = dict(item)
        copied.pop('_started_at_ms', None)
        files = [self._resolve_artifact_file_view(file_item) for file_item in item.get('files') or []]
        copied['files'] = files
        copied['file_count'] = len(files)
        copied['has_files'] = bool(files)
        return copied

    @staticmethod
    def _apply_quick_history_move_flags(pinned_items: list, normal_items: list):
        for index, item in enumerate(pinned_items):
            item['can_move_up'] = index > 0
            item['can_move_down'] = index < len(pinned_items) - 1
        for item in normal_items:
            item['can_move_up'] = False
            item['can_move_down'] = False

    def _build_pinned_quick_item(self, pinned_item: dict, latest_entry: dict | None) -> dict:
        command_text = str(pinned_item.get('command') or '').strip()
        snapshot = pinned_item.get('snapshot') if isinstance(pinned_item.get('snapshot'), dict) else {}
        source_item = latest_entry if isinstance(latest_entry, dict) else snapshot
        copied = dict(source_item or {})
        copied.pop('output_records', None)
        copied['command'] = command_text
        copied['raw_command'] = str(copied.get('raw_command') or command_text).strip()
        copied['is_pinned'] = True
        copied['pinned_at'] = str(pinned_item.get('pinned_at') or '').strip()
        copied['pin_order'] = int(pinned_item.get('pin_order', 0) or 0)
        return self._refresh_file_status_for_view(copied)

    def _build_normal_quick_item(self, item: dict) -> dict:
        copied = dict(item)
        copied.pop('output_records', None)
        copied['is_pinned'] = False
        copied['pinned_at'] = ''
        copied['pin_order'] = 0
        return self._refresh_file_status_for_view(copied)

    def _build_quick_history(self, machine_id: str) -> list:
        pinned_source_items = self.store.pinned_store.get_items(machine_id)
        pinned_commands = {item['command'] for item in pinned_source_items}
        pinned_items = []
        for pinned_item in pinned_source_items:
            command = pinned_item['command']
            pinned_items.append(
                self._build_pinned_quick_item(
                    pinned_item,
                    self.store._get_latest_entry_for_command(machine_id, command),
                )
            )

        normal_items = [
            self._build_normal_quick_item(item)
            for item in self.store._list_recents(machine_id)
            if str(item.get('command') or '').strip() not in pinned_commands
        ]
        self._apply_quick_history_move_flags(pinned_items, normal_items)
        result = pinned_items + normal_items
        for index, item in enumerate(result, start=1):
            item['index'] = index
        return result

    def _build_execution_entry_view(self, entry: dict, index: int = 0) -> dict:
        copied = self._refresh_file_status_for_view(entry)
        copied['output_records'] = list(entry.get('output_records') or [])
        if index > 0:
            copied['index'] = index
        return copied

    @staticmethod
    def _encode_cursor(started_at_ms: int, entry_id: str) -> str:
        payload = json.dumps({'t': int(started_at_ms), 'id': str(entry_id)}, separators=(',', ':')).encode('utf-8')
        return base64.urlsafe_b64encode(payload).decode('ascii').rstrip('=')

    @staticmethod
    def _decode_cursor(cursor: str):
        text = str(cursor or '').strip()
        if not text:
            return None
        try:
            padding = '=' * ((4 - len(text) % 4) % 4)
            payload = json.loads(base64.urlsafe_b64decode((text + padding).encode('ascii')).decode('utf-8'))
            return int(payload['t']), str(payload['id'])
        except Exception as exc:
            raise ValueError('Invalid history cursor') from exc

    @staticmethod
    def _normalize_page_limit(limit) -> int:
        try:
            value = int(limit)
        except Exception:
            value = COMMAND_HISTORY_PAGE_SIZE
        return min(max(value, 1), COMMAND_HISTORY_MAX_PAGE_SIZE)

    def get_history_for_connection(self, conn) -> list:
        if conn is None:
            return []
        return self.get_history_by_machine_id(self.store._get_machine_id_from_conn(conn))

    def get_history_by_machine_id(self, machine_id: str) -> list:
        machine_id_text = str(machine_id or '').strip() or 'unknown_machine'
        with self.store._lock:
            return self._build_quick_history(machine_id_text)

    def get_connection_command_counts_by_machine_id(self, machine_id: str) -> dict[str, int]:
        machine_id_text = str(machine_id or '').strip() or 'unknown_machine'
        rows = self.store.database.connection().execute(
            """
            SELECT client_id, COUNT(*) AS command_count
            FROM command_executions
            WHERE machine_id = ?
            GROUP BY client_id
            """,
            (machine_id_text,),
        ).fetchall()
        return {str(row['client_id'] or ''): int(row['command_count'] or 0) for row in rows}

    def get_connection_command_page(
        self,
        machine_id: str,
        client_id: str,
        *,
        limit=None,
        cursor: str = '',
    ) -> dict:
        machine_id_text = str(machine_id or '').strip() or 'unknown_machine'
        client_id_text = str(client_id or '').strip()
        if not client_id_text:
            raise ValueError('Invalid client id')

        page_limit = self._normalize_page_limit(limit)
        decoded_cursor = self._decode_cursor(cursor)
        rows = self.store._list_execution_rows(
            machine_id_text,
            limit=page_limit + 1,
            cursor=decoded_cursor,
            client_id=client_id_text,
        )
        has_more = len(rows) > page_limit
        page_rows = rows[:page_limit]
        items = [
            {
                'time': row['started_at'] or '',
                'status': row['status'] or '',
                'command': row['command'] or '',
                'duration_ms': int(row['duration_ms'] or 0),
            }
            for row in page_rows
        ]
        next_cursor = ''
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = self._encode_cursor(int(last['started_at_ms'] or 0), last['entry_id'])

        total_row = self.store.database.connection().execute(
            'SELECT COUNT(*) FROM command_executions WHERE machine_id = ? AND client_id = ?',
            (machine_id_text, client_id_text),
        ).fetchone()
        return {
            'items': items,
            'next_cursor': next_cursor,
            'has_more': has_more,
            'total_count': int(total_row[0] if total_row else 0),
        }

    def get_execution_history_page(self, machine_id: str, *, limit=None, cursor: str = '', query: str = '') -> dict:
        machine_id_text = str(machine_id or '').strip() or 'unknown_machine'
        query_text = str(query or '').strip()
        page_limit = self._normalize_page_limit(limit)
        decoded_cursor = self._decode_cursor(cursor)
        rows = self.store._list_execution_rows(
            machine_id_text,
            limit=page_limit + 1,
            cursor=decoded_cursor,
            query=query_text,
        )
        has_more = len(rows) > page_limit
        page_rows = rows[:page_limit]
        items = [
            self._build_execution_entry_view(self.store._row_to_entry(row), index=index)
            for index, row in enumerate(page_rows, start=1)
        ]
        next_cursor = ''
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = self._encode_cursor(int(last['started_at_ms'] or 0), last['entry_id'])

        count_sql = 'SELECT COUNT(*) FROM command_executions WHERE machine_id = ?'
        count_params = [machine_id_text]
        if query_text:
            count_sql += ' AND instr(LOWER(command), LOWER(?)) > 0'
            count_params.append(query_text)
        total_row = self.store.database.connection().execute(count_sql, tuple(count_params)).fetchone()
        return {
            'items': items,
            'next_cursor': next_cursor,
            'has_more': has_more,
            'total_count': int(total_row[0] if total_row else 0),
        }
