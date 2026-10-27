from server.application.preferences.settings_store import SettingsStore


ALLOWED_TERMINAL_CONTEXT_FIELD_IDS = frozenset({
    'status',
    'hostname',
    'address',
    'client_id',
    'os_type',
    'platform',
    'os_name',
    'os_version',
    'os_alias',
    'arch',
    'manufacturer',
    'model',
    'integrity',
    'build_version',
    'client_revision',
    'machine_id',
    'fingerprint_basis',
    'last_seen',
    'connected_at',
    'disconnected_at',
    'rtt',
    'working_directory',
    'pid',
    'process_name',
    'launch_command',
    'launch_mode',
    'client_log',
    'username',
    'python_version',
})


class TerminalContextPreferenceStore:
    """Server-global selection of connection fields shown below Terminal input."""

    def __init__(self, database):
        self.settings = SettingsStore(database, 'terminal_context_preferences')

    def get_preferences(self) -> dict:
        return self._normalize(self.settings.read())

    def save_preferences(self, payload: dict) -> dict:
        normalized = self._normalize(payload)
        self.settings.write(normalized)
        return normalized

    @staticmethod
    def _normalize(payload: dict) -> dict:
        source = payload if isinstance(payload, dict) else {}
        raw_field_ids = source.get('field_ids')
        if not isinstance(raw_field_ids, list):
            return {'field_ids': []}

        field_ids = []
        seen = set()
        for raw_field_id in raw_field_ids:
            field_id = str(raw_field_id or '').strip()
            if field_id not in ALLOWED_TERMINAL_CONTEXT_FIELD_IDS or field_id in seen:
                continue
            seen.add(field_id)
            field_ids.append(field_id)
        return {'field_ids': field_ids}
