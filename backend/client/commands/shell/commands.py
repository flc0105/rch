from client.commands.shell.base import CommandBase
from client.commands.shell.groups import (
    CommonFileCommands,
    CommonRuntimeCommands,
    CommonShellCommands,
)


class CommonCommands(
    CommonShellCommands,
    CommonFileCommands,
    CommonRuntimeCommands,
    CommandBase,
):
    """
    跨平台通用命令集合。

    这里不直接堆一长串零散 mixin。
    通用命令先按领域归组，再由平台命令类继承。
    """
    pass