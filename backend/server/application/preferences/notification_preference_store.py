from server.application.preferences.settings_store import SettingsStore


DEFAULT_NOTIFICATION_PREFERENCES = {
    'version': 1,
    'enabled': True,
    'events': {
        'connection_online': True,
        'connection_offline': True,
        'device_event': True,
        'artifact_created': True,
        'file_transfer_started': False,
        'file_transfer_stopped': False,
        'file_transfer_error': True,
        'pty_opened': True,
        'pty_closed': True,
        'pty_error': True,
        'screen_view_started': True,
        'screen_view_closed': True,
        'screen_view_error': True,
        'background_job_running': True,
        'background_job_stopped': True,
        'background_job_error': True,
        'external_tool_daemon_started': True,
        'external_tool_daemon_stopped': True,
        'external_tool_daemon_error': True,
        'external_tool_install_completed': True,
        'external_tool_install_failed': True,
        'external_tool_uninstall_completed': False,
        'external_tool_uninstall_failed': False,
        'agent_build_completed': True,
        'agent_build_error': True,
        'server_cleanup_completed': True,
    },
}


class NotificationPreferenceStore:
    """Shared SSE notification preferences stored in rch.db."""

    def __init__(self, database):
        self.settings = SettingsStore(database, 'notification_preferences')

    def get_preferences(self) -> dict:
        return self._normalize(self.settings.read())

    def save_preferences(self, payload: dict) -> dict:
        normalized = self._normalize(payload)
        self.settings.write(normalized)
        return normalized

    @staticmethod
    def _normalize_bool(value, default: bool) -> bool:
        return value if isinstance(value, bool) else default

    def _normalize(self, payload: dict) -> dict:
        source = payload if isinstance(payload, dict) else {}
        source_events = source.get('events') if isinstance(source.get('events'), dict) else {}
        events = {
            event_key: self._normalize_bool(source_events.get(event_key), default_value)
            for event_key, default_value in DEFAULT_NOTIFICATION_PREFERENCES['events'].items()
        }
        return {
            'version': DEFAULT_NOTIFICATION_PREFERENCES['version'],
            'enabled': self._normalize_bool(source.get('enabled'), DEFAULT_NOTIFICATION_PREFERENCES['enabled']),
            'events': events,
        }
