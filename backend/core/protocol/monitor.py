MONITOR_SUPPORTED_CHANNELS = frozenset({
    'system',
    'storage',
    'network',
    'battery',
    'processes',
    'apps',
    'process_detail',
    'process_connections',
    'process_open_files',
})
MONITOR_DEFAULT_CHANNELS = ('system', 'storage', 'network', 'battery')
MONITOR_DEFAULT_INTERVALS = {
    'system': 0.5,
    'network': 0.5,
    'storage': 5.0,
    'battery': 5.0,
    'processes': 1.0,
    'apps': 1.0,
    'process_detail': 1.0,
    'process_connections': 2.0,
    'process_open_files': 3.0,
}
MONITOR_MIN_INTERVAL_SECONDS = 0.25
MONITOR_MAX_INTERVAL_SECONDS = 60.0


def normalize_monitor_channels(channels) -> list[str]:
    raw = channels if isinstance(channels, (list, tuple, set)) else []
    normalized = []
    for channel in raw:
        name = str(channel or '').strip().lower()
        if name in MONITOR_SUPPORTED_CHANNELS and name not in normalized:
            normalized.append(name)
    return normalized or list(MONITOR_DEFAULT_CHANNELS)


def normalize_monitor_intervals(intervals, channels) -> dict:
    raw = intervals if isinstance(intervals, dict) else {}
    result = {}
    for channel in channels:
        default = MONITOR_DEFAULT_INTERVALS[channel]
        try:
            value = float(raw.get(channel, default))
        except Exception:
            value = default
        result[channel] = max(
            MONITOR_MIN_INTERVAL_SECONDS,
            min(MONITOR_MAX_INTERVAL_SECONDS, value),
        )
    return result


def normalize_monitor_options(options) -> dict:
    return dict(options) if isinstance(options, dict) else {}
