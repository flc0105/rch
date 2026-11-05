"""Post-commit runtime configuration effects (separate from persistence and value reads)."""

from client.config import runtime_config
from core.utils.logger import logger
from core.utils.output_marker import success, warning


class RuntimeConfigEffects:
    """Register only settings that require an action beyond reading the new value."""

    WATCHDOG_CONFIG_KEYS = {
        'REMOTE_CONTROL_WATCHDOG_ENABLED',
        'REMOTE_CONTROL_WATCHDOG_INTERVAL_SECONDS',
        'LOCAL_HEARTBEAT_WATCHDOG_ENABLED',
        'LOCAL_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS',
        'LOCAL_HEARTBEAT_WATCHDOG_TIMEOUT_SECONDS',
    }

    def __init__(self, owner, is_launchd_managed_client):
        self.owner = owner
        self.is_launchd_managed_client = is_launchd_managed_client
        self._callbacks = {}
        self.register(('SCREEN_FRAME_STRATEGY',), self._screen_strategy_notice)
        self.register(('PROCESS_RECOVERY_WATCHDOG_ENABLED',), self._apply_watchdog_update)
        self.register(self.WATCHDOG_CONFIG_KEYS, self._apply_watchdog_update)

    def register(self, keys, callback):
        for key in keys:
            self._callbacks.setdefault(key, []).append(callback)

    def apply(self, key, value):
        messages = []
        for callback in self._callbacks.get(key, ()):
            messages.extend(callback(key, value))
        return messages

    def _screen_strategy_notice(self, _key, _value):
        return [warning('Applies to new Screen View sessions; restart the current Screen View to switch mode')]

    def _apply_watchdog_update(self, key, value):
        effects = []
        launchd_managed = self.is_launchd_managed_client()
        watchdog_supported = bool(getattr(getattr(self.owner.socket, 'runtime', None), 'features', {}).get('watchdog', True))

        if key == 'PROCESS_RECOVERY_WATCHDOG_ENABLED':
            if not watchdog_supported:
                effects.append(warning('Saved: watchdog is unavailable on this Client; restart with watchdog support to apply'))
            manager = getattr(self.owner.socket, 'process_recovery_watchdog_manager', None) if watchdog_supported else None
            if manager is not None:
                self.owner._checkpoint()
                try:
                    if value and not launchd_managed:
                        manager.start()
                    else:
                        manager.stop()
                except Exception as exc:
                    logger.warning('Process Recovery Watchdog runtime update failed: %s', exc)
                    effects.append(warning(f'Saved: Process Recovery Watchdog could not start/stop: {exc}'))
                else:
                    if launchd_managed:
                        effects.append(warning('Saved: launchd manages this Client; Process Recovery Watchdog remains disabled'))
                    else:
                        effects.append(success('Applied: Process Recovery Watchdog runtime updated'))
                    # Remote Control Watchdog / Local Heartbeat Watchdog workers inherit the supervisor environment at launch.
                    if (runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED
                            or runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED):
                        if not self._restart_watchdog_manager():
                            effects.append(warning('Saved: Remote Control Watchdog / Local Heartbeat Watchdog worker could not restart'))
                self.owner._checkpoint()

        if key in self.WATCHDOG_CONFIG_KEYS:
            if not watchdog_supported:
                effects.append(warning('Saved: watchdog is unavailable on this Client; restart with watchdog support to apply'))
            elif self._restart_watchdog_manager():
                if launchd_managed:
                    effects.append(warning('Saved: launchd manages this Client; Client watchdogs remain disabled'))
                else:
                    effects.append(success('Applied: watchdog runtime restarted'))
            else:
                effects.append(warning('Saved: watchdog worker did not restart; check Client logs'))

        return effects

    def _restart_watchdog_manager(self) -> bool:
        watchdog_manager = getattr(self.owner.socket, 'watchdog_manager', None)
        if watchdog_manager is None:
            return False

        try:
            self.owner._checkpoint()
            watchdog_manager.stop()
            self.owner._checkpoint()
            watchdog_manager.start()
            self.owner._checkpoint()
            return True
        except Exception as e:
            logger.warning(f'Failed to restart watchdog runtime after config update: {e}')
            return False
