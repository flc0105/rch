from client.commands.arguments.models import ArgumentCommandSpec


def argument_command(name: str, spec: ArgumentCommandSpec | None = None, *, api_grants=()):
    """
    标记一个 acmd 实验命令处理方法
    """
    def decorator(func):
        func.argument_command_name = name
        func.argument_command_spec = spec
        func.argument_command_grants = tuple(api_grants)
        return func
    return decorator
