from functools import wraps
import re




def _strip_confirm_bypass(arg):
    """Extract an explicit leading/trailing --no-confirm from a Client command argument."""
    if not isinstance(arg, str):
        return False, arg
    if re.match(r'^\s*--no-confirm(?=\s|$)', arg):
        return True, re.sub(r'^\s*--no-confirm(?=\s|$)\s*', '', arg, count=1)
    if re.search(r'(?<=\s)--no-confirm\s*$', arg):
        return True, re.sub(r'\s+--no-confirm\s*$', '', arg, count=1)
    return False, arg


def confirm(message=None):
    """Require a Client Interaction Broker confirmation before calling a command.

    Works with @shell_command in either order; no changes to the command body are needed.
    """
    def decorator(func):
        prompt = message if message is not None else f"Execute command '{func.__name__}'?"
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('Confirmation message must be a nonempty string')

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            raw_arg = args[0] if args else kwargs.get('options', '')
            bypass, cleaned = _strip_confirm_bypass(raw_arg)
            if bypass:
                if args:
                    args = (cleaned, *args[1:])
                elif 'options' in kwargs:
                    kwargs['options'] = cleaned
                return func(self, *args, **kwargs)
            from client.runtime.execution.interaction_service import CommandInteractions

            try:
                approved = CommandInteractions(self).confirm(
                    prompt, title='Confirm command execution',
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
