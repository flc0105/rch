from client.commands.common.mixins.execution_ops import CommandExecutionMixin
from client.commands.common.mixins.external_tool_ops import CommandExternalToolMixin
from client.commands.common.mixins.file_cli_ops import CommandFileCliMixin
from client.commands.common.mixins.file_web_ops import CommandFileWebMixin
from client.commands.common.mixins.introspection_ops import CommandIntrospectionMixin
from client.commands.common.mixins.process_ops import CommandProcessMixin
from client.commands.common.mixins.runtime_config_ops import CommandRuntimeConfigMixin
from client.commands.common.mixins.session_ops import CommandSessionMixin
from client.commands.common.mixins.system_ops import CommandSystemMixin
from client.commands.common.mixins.update_ops import CommandUpdateMixin
from client.commands.common.mixins.watchdog_ops import CommandWatchdogMixin


class CommonShellCommands(
    CommandExecutionMixin,
    CommandSessionMixin,
    CommandSystemMixin,
):
    """
    shell-like / session / system 通用命令组。
    """
    pass


class CommonFileCommands(
    CommandFileCliMixin,
    CommandFileWebMixin,
):
    """
    文件传输和远程文件管理命令组。
    """
    pass


class CommonRuntimeCommands(
    CommandExternalToolMixin,
    CommandIntrospectionMixin,
    CommandProcessMixin,
    CommandRuntimeConfigMixin,
    CommandWatchdogMixin,
    CommandUpdateMixin,
):
    """
    client runtime 管理类命令组。
    """
    pass