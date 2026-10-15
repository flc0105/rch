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
        setattr(func, 'api_grants', tuple(api_grants))
        return func

    return attr_decorator