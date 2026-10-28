"""Client launch-time feature choices. Restart the Client after changing overrides.

Only explicitly configurable features appear in FEATURE_OVERRIDES. Missing keys
use platform defaults. PTY/Screen/Clipboard/Watchdog disable imports;
external_tool and process_monitor only control Web entry availability.
"""

# Edit these values locally. Accepted keys are listed in _DEFAULTS below.
# Example: {'screen_view': False, 'screen_input': False, 'pty': False}
# external_tool and process_monitor control Web entry availability; their shared
# runtime code may still be imported by Script / commands / Device Monitor.
FEATURE_OVERRIDES = {}

_DEFAULTS = {
    'mac': {'external_tool': True, 'process_monitor': True, 'pty': True, 'screen_view': True, 'screen_input': True, 'clipboard': True, 'watchdog': True},
    'win': {'external_tool': True, 'process_monitor': True, 'pty': True, 'screen_view': True, 'screen_input': True, 'clipboard': True, 'watchdog': True},
    'linux': {'external_tool': True, 'process_monitor': True, 'pty': True, 'screen_view': False, 'screen_input': False, 'clipboard': False, 'watchdog': True},
    'ios': {'external_tool': False, 'process_monitor': False, 'pty': False, 'screen_view': False, 'screen_input': False, 'clipboard': True, 'watchdog': False},
}

def resolve_features(os_alias=None, overrides=None):
    """Return effective, immutable-for-this-startup capability choices."""
    if os_alias is None:
        from core.device.local_identity import get_local_identity
        os_alias = get_local_identity().os_alias
    defaults = dict(_DEFAULTS.get(os_alias, _DEFAULTS['linux']))
    chosen = FEATURE_OVERRIDES if overrides is None else overrides
    if not isinstance(chosen, dict):
        raise ValueError('FEATURE_OVERRIDES must be a dict')
    for name, state in chosen.items():
        if name not in defaults:
            raise ValueError(f'Unknown Client feature: {name}')
        if type(state) is not bool:
            raise ValueError(f'Client feature {name} must be boolean')
        defaults[name] = state

    if not defaults['screen_view']:
        defaults['screen_input'] = False
    if os_alias not in _DEFAULTS:
        defaults['watchdog'] = False
        defaults['external_tool'] = False
        defaults['process_monitor'] = False
    if os_alias == 'ios':
        defaults['pty'] = False
        defaults['screen_view'] = False
        defaults['screen_input'] = False
        defaults['watchdog'] = False
        defaults['external_tool'] = False
        defaults['process_monitor'] = False
    return defaults
