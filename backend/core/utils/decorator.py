from functools import wraps



def desc(text, group='general', suggest=True, api_grants=()):
    """
    装饰器函数，用于为函数或方法添加命令元信息。

    Args:
        text (str): 帮助文案
        group (str): 命令分组
        suggest (bool): 是否默认出现在自动补全候选中
        api_grants (tuple): 命令请求的 API 授权范围

    Returns:
        function: 装饰后的函数或方法对象
    """

    def attr_decorator(func):
        setattr(func, 'help', text)
        setattr(func, 'group', group)
        setattr(func, 'suggest', suggest)
        # Preserve scopes declared by independent method decorators such as @confirm.
        setattr(func, 'api_grants', tuple(dict.fromkeys(
            (*getattr(func, 'api_grants', ()), *api_grants)
        )))
        return func

    return attr_decorator


def confirm(message=None):
    """Require a Client Interaction Broker confirmation before calling a command.

    Works with @desc in either order; no changes to the command body are needed.
    Only exported Client commands receive automatic Server-issued grants.
    """
    def decorator(func):
        prompt = message if message is not None else f"Execute command '{func.__name__}'?"
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('Confirmation message must be a nonempty string')

        @wraps(func)
        def wrapper(self, *args, **kwargs):
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
        wrapper.api_grants = tuple(dict.fromkeys(
            (*getattr(func, 'api_grants', ()), 'interactions:request')
        ))
        return wrapper

    if callable(message):
        func = message
        message = None
        return decorator(func)
    return decorator
