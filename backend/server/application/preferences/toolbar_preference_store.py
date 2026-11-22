import re

from server.application.preferences.settings_store import SettingsStore


# Toolbar action and icon catalogs are defined by the frontend. This store owns
# persistence and structure only; no second list of UI actions is kept here.
_PREFERENCE_ID_PATTERN = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')


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
        for item in value[:128]:
            action_id = str(item or '').strip()
            if not _PREFERENCE_ID_PATTERN.fullmatch(action_id) or action_id in seen:
                continue
            seen.add(action_id)
            result.append(action_id)
        return result


    @staticmethod
    def _normalize_quick_action_pins(value) -> list[dict]:
        if not isinstance(value, list):
            return []
        result = []
        seen = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            platform = str(item.get('platform') or '').strip().lower()
            alias = str(item.get('alias') or '').strip()
            if not platform or not alias:
                continue
            key = (platform, alias)
            if key in seen:
                continue
            seen.add(key)
            result.append({'platform': platform, 'alias': alias})
        return result

    @staticmethod
    def _normalize_toolbox_shortcuts(value) -> list[dict]:
        if not isinstance(value, list):
            return []
        result, seen = [], set()
        for raw in value:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get('kind') or '').strip()
            icon = str(raw.get('icon') or '').strip()
            label = str(raw.get('label') or '').strip()[:64]
            if not _PREFERENCE_ID_PATTERN.fullmatch(icon):
                continue
            if kind == 'script':
                name = str(raw.get('script_name') or '').strip()
                if not name:
                    continue
                key = ('script', name)
                item = {'kind': kind, 'script_name': name, 'icon': icon}
            elif kind == 'quick_action':
                platform = str(raw.get('platform') or '').strip().lower()
                alias = str(raw.get('alias') or '').strip()
                if not platform or not alias:
                    continue
                key = ('quick_action', platform, alias)
                item = {'kind': kind, 'platform': platform, 'alias': alias, 'icon': icon}
            else:
                continue
            if key in seen:
                continue
            if label:
                item['label'] = label
            seen.add(key)
            result.append(item)
        return result

    def _normalize(self, payload: dict) -> dict:
        source = payload if isinstance(payload, dict) else {}
        toolbar = self._normalize_list(source.get('toolbar'))
        more = self._normalize_list(source.get('more'))
        # Keep one placement per action; frontend owns which actions exist and
        # supplies default placement for additions to its catalog.
        toolbar = toolbar[:64]
        toolbar_set = set(toolbar)
        more = [action_id for action_id in more if action_id not in toolbar_set][:64]
        return {
            'toolbar': toolbar,
            'more': more,
            'quick_actions_pinned': self._normalize_quick_action_pins(source.get('quick_actions_pinned')),
            'toolbox_shortcuts': self._normalize_toolbox_shortcuts(source.get('toolbox_shortcuts')),
        }
