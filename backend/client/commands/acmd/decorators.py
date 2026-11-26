from core.commands.argument_models import ArgumentCommandSpec
from core.platform.normalization import normalize_platform_alias


_VALID_PLATFORMS = frozenset({'mac', 'win', 'linux', 'ios'})


def argument_command(name: str, spec: ArgumentCommandSpec | None = None, *,
                     may_interact=False, output='collect', platforms=None):
    """
    标记一个 acmd 实验命令处理方法
    """
    if output not in ('collect', 'stream'):
        raise ValueError('Command output must be collect or stream')
    if platforms is None:
        supported = None
    else:
        if isinstance(platforms, str):
            raise TypeError('platforms must be a non-empty sequence, e.g. ("mac",)')
        try:
            candidates = tuple(platforms)
        except TypeError as exc:
            raise TypeError('platforms must be a sequence') from exc
        supported = tuple(dict.fromkeys(
            normalize_platform_alias(value) for value in candidates
        ))
        if not supported or any(alias not in _VALID_PLATFORMS for alias in supported):
            raise ValueError('platforms must name one or more of mac, win, linux, ios')
    def decorator(func):
        func.command_output = output
        func.argument_command_name = name
        func.argument_command_spec = spec
        func.command_may_interact = bool(may_interact)
        func.argument_command_platforms = supported
        return func
    return decorator
