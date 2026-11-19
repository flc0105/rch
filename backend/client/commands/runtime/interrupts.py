"""Declarative command execution policy (not a force-interruption mechanism)."""

from collections.abc import Mapping

from core.utils.timeouts import normalize_positive_timeout


def timeout(seconds: float | Mapping[str, float]):
    """Declare a shared budget or a budget for each supported platform."""
    if isinstance(seconds, Mapping):
        budgets = {platform: normalize_positive_timeout(value) for platform, value in seconds.items()}
        if not budgets or any(value is None for value in budgets.values()):
            raise ValueError('Command timeout must be positive')

        def decorator(func):
            func.command_platform_timeouts = budgets
            return func
    else:
        value = normalize_positive_timeout(seconds)
        if value is None:
            raise ValueError('Command timeout must be positive')

        def decorator(func):
            func.command_timeout = value
            return func
    return decorator


def get_command_timeout(handler, platform=None):
    budgets = getattr(handler, 'command_platform_timeouts', {})
    return budgets.get(platform, getattr(handler, 'command_timeout', None))


def cancel_policy(mode: str = 'none', message: str = ''):
    """Declare the execution mechanism: none, cooperative, or managed subprocess.

    This is metadata, not a wrapper or a guarantee of stopping arbitrary Python code.
    """
    if mode not in ('none', 'cooperative', 'process'):
        raise ValueError('Cancel mode must be none, cooperative or process')

    def decorator(func):
        func.command_cancel_mode = mode
        func.command_cancel_message = str(message or '').strip()
        return func
    return decorator
