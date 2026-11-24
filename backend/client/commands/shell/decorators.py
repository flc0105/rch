"""Registration metadata for ordinary Client shell-like commands."""

from functools import wraps

from core.command_completion.models import CompletionSpec
from core.platform.normalization import normalize_platform_alias

_VALID_PLATFORMS = frozenset({'mac', 'win', 'linux', 'ios'})


def shell_command(description, group='general', suggest=True, *, output='collect',
                  interaction=False, completion=None, platforms=None):
    """Mark an ordinary Client command; platforms=None enables all platforms.

    The original free-text argument convention is unchanged. CompletionSpec
    declares optional argument completion, not an ACMD argument schema.
    """
    if output not in ('collect', 'stream'):
        raise ValueError('Command output must be collect or stream')
    if completion is not None and not isinstance(completion, CompletionSpec):
        completion = CompletionSpec.from_dict(completion)
    if platforms is None:
        supported = None
    else:
        if isinstance(platforms, str):
            raise TypeError('platforms must be a non-empty sequence, e.g. ("mac",)')
        try:
            items = tuple(platforms)
        except TypeError as exc:
            raise TypeError('platforms must be a sequence') from exc
        supported = tuple(dict.fromkeys(normalize_platform_alias(value) for value in items))
        if not supported or any(value not in _VALID_PLATFORMS for value in supported):
            raise ValueError('platforms must name one or more of mac, win, linux, ios')

    def decorator(func):
        func.command_output = output
        func.command_interaction = bool(interaction)
        if completion is not None:
            func.command_completion = completion
        func.help = description
        func.group = group
        func.suggest = suggest
        func.command_platforms = supported
        return func
    return decorator


def supports_shell_platform(handler, platform):
    """Return whether an exported Shell command is enabled on this Client."""
    supported = getattr(handler, 'command_platforms', None)
    return supported is None or normalize_platform_alias(platform) in supported


def reverse_only(message):
    """Reject instance operations unsupported by a fixed-port Bind listener before confirmation."""
    def decorate(handler):
        @wraps(handler)
        def guarded(self, *args, **kwargs):
            from client.config.config import RUNTIME_CONFIG
            if RUNTIME_CONFIG.get('connection_mode') == 'bind':
                return 0, message
            return handler(self, *args, **kwargs)
        return guarded
    return decorate
