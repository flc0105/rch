from server.application.preferences.settings_store import SettingsStore


DEFAULT_TOOLBAR_PREFERENCES = {
    'toolbar': [
        'remote-files', 'artifacts', 'info', 'scripts', 'history', 'pty', 'screen-view', 'clipboard',
    ],
    'more': [
        'external-tools', 'jobs', 'agents', 'processes', 'keychains', 'one-liners', 'quick-actions',
    ],
}

_ALLOWED_ACTION_IDS = tuple(DEFAULT_TOOLBAR_PREFERENCES['toolbar'] + DEFAULT_TOOLBAR_PREFERENCES['more'])


class ToolbarPreferenceStore:
    """Shared toolbar layout preferences stored in rch.db."""

    def __init__(self, database):
        self.settings = SettingsStore(database, 'toolbar_preferences')

    def get_preferences(self) -> dict:
        return self._normalize(self.settings.read())

    def save_preferences(self, payload: dict) -> dict:
        normalized = self._normalize(payload)
        self.settings.write(normalized)
        return normalized

    @staticmethod
    def _normalize_list(value) -> list[str]:
        if not isinstance(value, list):
            return []
        result = []
        seen = set()
        for item in value:
            action_id = str(item or '').strip()
            if action_id not in _ALLOWED_ACTION_IDS or action_id in seen:
                continue
            seen.add(action_id)
            result.append(action_id)
        return result

    def _normalize(self, payload: dict) -> dict:
        source = payload if isinstance(payload, dict) else {}
        toolbar = self._normalize_list(source.get('toolbar'))
        more = self._normalize_list(source.get('more'))
        used = set(toolbar + more)
        for action_id in _ALLOWED_ACTION_IDS:
            if action_id in used:
                continue
            if action_id in DEFAULT_TOOLBAR_PREFERENCES['toolbar']:
                toolbar.append(action_id)
            else:
                more.append(action_id)
            used.add(action_id)
        return {'toolbar': toolbar, 'more': more}
