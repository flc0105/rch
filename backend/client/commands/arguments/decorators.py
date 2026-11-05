from client.commands.arguments.models import ArgumentCommandSpec


def argument_command(name: str, spec: ArgumentCommandSpec | None = None, *, interaction=False, output='collect'):
    """
    标记一个 acmd 实验命令处理方法
    """
    if output not in ('collect', 'stream'):
        raise ValueError('Command output must be collect or stream')
    def decorator(func):
        func.command_output = output
        func.argument_command_name = name
        func.argument_command_spec = spec
        func.command_interaction = bool(interaction)
        return func
    return decorator
