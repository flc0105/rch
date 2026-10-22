from server.application.preferences.settings_store import SettingsStore


DEFAULT_TOOLBAR_PREFERENCES = {
    'toolbar': [
        'remote-files', 'artifacts', 'info', 'scripts', 'history', 'pty', 'screen-view', 'clipboard',
    ],
    'more': [
        'external-tools', 'jobs', 'agents', 'processes', 'keychains', 'one-liners', 'quick-actions',
    ],
    'quick_actions_pinned': [],
    'toolbox_shortcuts': [],
}

_ALLOWED_ACTION_IDS = tuple(DEFAULT_TOOLBAR_PREFERENCES['toolbar'] + DEFAULT_TOOLBAR_PREFERENCES['more'])


_TOOLBOX_ICONS = frozenset({
    'file-code', 'terminal', 'zap', 'rocket', 'play', 'activity', 'shield-check',
    'folder-open', 'monitor', 'wrench', 'calendar-clock', 'book-open', 'code-2',
    'archive', 'clipboard', 'scroll-text',
    'star', 'heart', 'check-circle', 'circle-alert', 'bell', 'bookmark', 'flag',
    'folder', 'folder-code', 'file-text', 'file-json', 'files', 'braces', 'bug',
    'git-branch', 'git-merge', 'git-pull-request', 'git-commit', 'box', 'boxes',
    'cpu', 'hard-drive', 'cloud', 'cloud-upload', 'cloud-download', 'download', 'upload',
    'settings', 'sliders-horizontal', 'database-backup', 'shield', 'lock', 'key-round',
    'refresh-ccw', 'repeat', 'timer', 'clock', 'calendar', 'list-checks', 'list-todo',
    'chart-no-axes-column', 'chart-line', 'eye', 'search', 'filter', 'link', 'globe-2',
    'network', 'wifi', 'send', 'mail', 'message-square', 'image', 'camera',
    'video', 'music', 'headphones', 'pencil', 'pen-line', 'trash-2', 'copy',
    'scissors', 'save', 'printer', 'power', 'plug', 'lightbulb', 'sun', 'moon',
})


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
            if icon not in _TOOLBOX_ICONS:
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
        used = set(toolbar + more)
        for action_id in _ALLOWED_ACTION_IDS:
            if action_id in used:
                continue
            if action_id in DEFAULT_TOOLBAR_PREFERENCES['toolbar']:
                toolbar.append(action_id)
            else:
                more.append(action_id)
            used.add(action_id)
        return {
            'toolbar': toolbar,
            'more': more,
            'quick_actions_pinned': self._normalize_quick_action_pins(source.get('quick_actions_pinned')),
            'toolbox_shortcuts': self._normalize_toolbox_shortcuts(source.get('toolbox_shortcuts')),
        }
