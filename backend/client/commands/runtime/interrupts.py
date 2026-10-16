"""Declarative command execution policy (not a force-interruption mechanism)."""

from core.utils.timeouts import normalize_positive_timeout


def timeout(seconds: float):
    """Declare the command's default budget; explicit request limits can only shorten it."""
    value = normalize_positive_timeout(seconds)
    if value is None:
        raise ValueError('Command timeout must be positive')

    def decorator(func):
        func.command_timeout = value
        return func
    return decorator


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
