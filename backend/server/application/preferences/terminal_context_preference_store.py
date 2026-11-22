import re

from server.application.preferences.settings_store import SettingsStore


# Field definitions belong to the frontend Connection Context catalog. The
# Server persists ordered field identifiers without maintaining a second list.
_FIELD_ID_PATTERN = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')


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
        for raw_field_id in raw_field_ids[:64]:
            if not isinstance(raw_field_id, str):
                continue
            field_id = raw_field_id.strip()
            if not _FIELD_ID_PATTERN.fullmatch(field_id) or field_id in seen:
                continue
            seen.add(field_id)
            field_ids.append(field_id)
        return {'field_ids': field_ids}
