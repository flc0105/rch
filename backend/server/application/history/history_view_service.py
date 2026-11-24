"""Read models for Activity Center and the independent Quick History."""
import base64
import json

from server.application.artifact.artifact_reference_view_projector import ArtifactReferenceViewProjector
from server.config.config import COMMAND_HISTORY_PAGE_SIZE, COMMAND_HISTORY_MAX_PAGE_SIZE
from server.application.history.activity_definitions import ActivityKind, activity_summary
from core.protocol.references import ReferenceType
from core.utils.command_output import project_result_output_texts


class HistoryViewService:
    def get_execution_entry(self, machine_id: str, activity_id: str):
        """Fetch one exact Activity record for reliable terminal output recovery."""
        entry = self.store.get_entry(machine_id, activity_id)
        return self._project_files(entry) if entry else None

    def __init__(self, store):
        self.store = store
        self.artifact_view_projector = ArtifactReferenceViewProjector()

    def _resolve_artifact(self, file_item):
        return self.artifact_view_projector.project(
            file_item, self.store.artifact_service,
            path_key='saved_path', allow_local_path_fallback=True, include_saved_at=True,
        )

    def _project_files(self, entry):
        texts = project_result_output_texts(entry.get('result') or [])
        if texts is not None:
            entry['output_texts'] = texts
        # Produced Files is the existing view of Artifact references, not another store.
        entry['files'] = [self._resolve_artifact(ref.get('snapshot') or {'artifact_id': ref['id']})
                          for ref in entry['references'] if ref['type'] == ReferenceType.ARTIFACT]
        entry['file_count'] = len(entry['files'])
        return entry

    @staticmethod
    def _apply_quick_history_move_flags(pinned, normal):
        for index, item in enumerate(pinned):
            item['can_move_up'] = index > 0
            item['can_move_down'] = index < len(pinned) - 1
        for item in normal:
            item['can_move_up'] = False
            item['can_move_down'] = False

    def _build_quick_history(self, machine_id):
        pinned_source = self.store.pinned_store.get_items(machine_id)
        pinned = []
        for item in pinned_source:
            command = item['command']
            recent = self.store.quick_store.get_recent(machine_id, command)
            snapshot = recent['snapshot'] if recent else item.get('snapshot') or {}
            pinned.append({**snapshot, 'command': command, 'is_pinned': True,
                           'pinned_at': item.get('pinned_at') or '', 'pin_order': item.get('pin_order') or 0,
                           'last_used_at': recent['last_used_at'] if recent else '',
                           'use_count': recent['use_count'] if recent else 0, 'files': []})
        pinned_commands = {row['command'] for row in pinned}
        normal = [{**row, 'files': [], 'is_pinned': False, 'pin_order': 0, 'pinned_at': ''}
                  for row in self.store.quick_store.list_recents(machine_id) if row['command'] not in pinned_commands]
        self._apply_quick_history_move_flags(pinned, normal)
        results = pinned + normal
        for index, row in enumerate(results, start=1):
            row['index'] = index
        return results

    @staticmethod
    def _encode_cursor(started_at_ms, activity_id):
        raw = json.dumps({'t': int(started_at_ms), 'id': str(activity_id)}, separators=(',', ':')).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')

    @staticmethod
    def _decode_cursor(cursor):
        if not str(cursor or '').strip():
            return None
        try:
            text = str(cursor).strip()
            payload = json.loads(base64.urlsafe_b64decode(text + '=' * (-len(text) % 4)))
            return int(payload['t']), str(payload['id'])
        except Exception as exc:
            raise ValueError('Invalid activity cursor') from exc

    @staticmethod
    def _limit(value):
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = COMMAND_HISTORY_PAGE_SIZE
        return min(max(result, 1), COMMAND_HISTORY_MAX_PAGE_SIZE)

    def get_history_for_connection(self, conn):
        return self.get_history_by_machine_id(self.store.machine_id_for_connection(conn)) if conn else []

    def get_history_by_machine_id(self, machine_id):
        with self.store.read_snapshot():
            return self._build_quick_history(str(machine_id or '').strip() or 'unknown_machine')

    def _activity_page(self, machine_id, *, client_id='', limit=None, cursor='', query='', kind='', errors=False, connection_summary=False):
        size = self._limit(limit)
        filters = {'client_id': client_id, 'query': query, 'kind': kind, 'errors': errors}
        rows = self.store.list_execution_rows(machine_id, limit=size + 1,
                                               cursor=self._decode_cursor(cursor), **filters)
        has_more = len(rows) > size
        page_rows = rows[:size]
        items = []
        for row in page_rows:
            entry = dict(row)
            if connection_summary:
                # Session timeline needs identity, status and a readable label only.
                # Avoid resolving artifacts or sending full command output to this list.
                items.append({
                    'activity_id': entry['activity_id'], 'kind': entry['kind'],
                    'action': entry['action'], 'summary': activity_summary(entry),
                    'status': entry['status'], 'created_at': entry['created_at'],
                    'started_at': entry['started_at'], 'finished_at': entry['finished_at'],
                })
            else:
                entry.pop('started_at_ms')
                entry['result_omitted'] = bool(entry['result_omitted'])
                items.append(entry)
        next_cursor = self._encode_cursor(page_rows[-1]['started_at_ms'], page_rows[-1]['activity_id']) if has_more and page_rows else ''
        # Count uses exactly the same filters as data, excluding page cursor.
        count = self.store.count_activities(machine_id, **filters)
        return {'items': items, 'next_cursor': next_cursor, 'has_more': has_more, 'total_count': count}

    def get_execution_history_page(self, machine_id, *, limit=None, cursor='', query='', kind='', errors=False):
        if kind and kind not in ActivityKind.ALL:
            raise ValueError('Invalid activity kind')
        with self.store.read_snapshot():
            return self._activity_page(str(machine_id or '').strip() or 'unknown_machine',
                                       limit=limit, cursor=cursor, query=query, kind=kind, errors=errors)

    def get_connection_command_counts_by_machine_id(self, machine_id, client_ids=None):
        ids = [str(value) for value in (client_ids or []) if str(value)]
        return self.store.count_by_client_ids(machine_id, ids)

    def get_connection_command_totals(self, machine_id):
        return self.store.connection_totals(machine_id)

    def get_connection_command_page(self, machine_id, client_id, *, limit=None, cursor=''):
        if not str(client_id or '').strip():
            raise ValueError('Invalid client id')
        with self.store.read_snapshot():
            return self._activity_page(str(machine_id or '').strip() or 'unknown_machine',
                                       client_id=client_id, limit=limit, cursor=cursor,
                                       connection_summary=True)
