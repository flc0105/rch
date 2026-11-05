from functools import wraps
import re



def desc(text, group='general', suggest=True, *, output='collect', interaction=False):
    """
    装饰器函数，用于为函数或方法添加命令元信息。

    Args:
        text (str): 帮助文案
        group (str): 命令分组
        suggest (bool): 是否默认出现在自动补全候选中
        output (str): collect (final result) or stream (progressive output)
        interaction (bool): 命令可能在执行中请求 Interaction Broker

    Returns:
        function: 装饰后的函数或方法对象
    """

    if output not in ('collect', 'stream'):
        raise ValueError('Command output must be collect or stream')

    def attr_decorator(func):
        setattr(func, 'command_output', output)
        setattr(func, 'command_interaction', bool(interaction))
        setattr(func, 'help', text)
        setattr(func, 'group', group)
        setattr(func, 'suggest', suggest)
        return func

    return attr_decorator


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

    Works with @desc in either order; no changes to the command body are needed.
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
            from client.commands.common.services.interaction_service import CommandInteractions

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
