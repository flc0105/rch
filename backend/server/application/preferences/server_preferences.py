"""Persistent Server-wide Web preferences, separate from Client runtime configuration."""

from server.application.preferences.settings_store import SettingsStore

DEFAULT_SERVER_PREFERENCES = {
    'ask_on_conflict': False,
    'preview_text_max_bytes': 512 * 1024,
    'log_viewer_max_chars': 512 * 1024,
}


class ServerPreferences:
    def __init__(self, database):
        self.store = SettingsStore(database, 'server_preferences')

    def read(self):
        stored = self.store.read()
        return {
            key: self._validate(key, stored.get(key, default))
            for key, default in DEFAULT_SERVER_PREFERENCES.items()
        }

    @staticmethod
    def _validate(key, value):
        if key == 'ask_on_conflict':
            if not isinstance(value, bool):
                raise ValueError('ask_on_conflict must be a boolean')
            return value
        if type(value) is not int or not (64 * 1024 <= value <= 8 * 1024 * 1024):
            raise ValueError(f'{key} must be between 64 Ki and 8 Mi units')
        return value

    def save(self, payload):
        if not isinstance(payload, dict) or set(payload) != set(DEFAULT_SERVER_PREFERENCES):
            raise ValueError('All Server preference fields are required')
        saved = {key: self._validate(key, value) for key, value in payload.items()}
        self.store.write(saved)
        return saved
