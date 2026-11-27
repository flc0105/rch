from functools import wraps
import re




def _strip_confirm_bypass(arg, *, separator_options=None):
    """Extract an explicit leading/trailing --no-confirm from a Client command argument."""
    if not isinstance(arg, str):
        return False, arg
    if separator_options is not None:
        options = '|'.join(re.escape(option) for option in ('--no-confirm', *separator_options))
        separator = re.match(rf'^\s*(?:(?:{options})\s+)*--(?=\s|$)', arg)
        if separator:
            start = separator.end() - 2
            bypass, prefix = _strip_confirm_bypass(arg[:start])
            if bypass:
                return True, (prefix.strip() + ' ' + arg[start:]).lstrip()
            return False, arg
    if re.match(r'^\s*--no-confirm(?=\s|$)', arg):
        return True, re.sub(r'^\s*--no-confirm(?=\s|$)\s*', '', arg, count=1)
    if re.search(r'(?<=\s)--no-confirm\s*$', arg):
        return True, re.sub(r'\s+--no-confirm\s*$', '', arg, count=1)
    return False, arg


def confirm(message=None, *, platform_messages=None, no_arguments=False, separator_options=None):
    """Require a Client Interaction Broker confirmation before calling a command.

    Works with @shell_command in either order; no changes to the command body are needed.
    """
    platform_messages = dict(platform_messages or {})
    if any(not isinstance(value, str) or not value.strip() for value in platform_messages.values()):
        raise ValueError('Confirmation message must be a nonempty string')

    def decorator(func):
        prompt = message if message is not None else f"Execute command '{func.__name__}'?"
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('Confirmation message must be a nonempty string')

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            raw_arg = args[0] if args else kwargs.get('options', '')
            bypass, cleaned = _strip_confirm_bypass(raw_arg, separator_options=separator_options)
            if no_arguments and cleaned.strip():
                return 0, f'Usage: {func.__name__} [--no-confirm]'
            if bypass:
                if args:
                    args = (cleaned, *args[1:])
                elif 'options' in kwargs:
                    kwargs['options'] = cleaned
                return func(self, *args, **kwargs)
            from client.runtime.execution.interaction_service import CommandInteractions

            try:
                approved = CommandInteractions(self).confirm(
                    platform_messages.get(getattr(self, 'command_platform', None), prompt),
                    title='Confirm command execution',
                )
            except Exception as exc:
                return 0, f'Command confirmation unavailable: {exc}'
            if not approved:
                return 0, 'Command cancelled: confirmation rejected or expired'
            return func(self, *args, **kwargs)

        wrapper.requires_confirmation = True
        return wrapper

    if callable(message):
        func = message
        message = None
        return decorator(func)
    return decorator
