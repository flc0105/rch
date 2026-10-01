from client.commands.arguments.registry import ArgumentCommandRegistry
from core.device.local_identity import get_local_identity


class CommandCatalog:
    """
    命令目录。

    职责：
    - 根据平台加载命令类
    - 缓存平台命令实例
    - 提供唯一的 acmd registry 归属点
    """

    # PLATFORM_COMMAND_MODULES = {
    #     'windows': ('client.commands.platform.win', 'WindowsCommands'),
    #     'darwin': ('client.commands.platform.mac', 'MacCommands'),
    #     'linux': ('client.commands.platform.linux', 'LinuxCommands'),
    #     'ios': ('client.commands.platform.ios', 'iOSCommands')
    # }
    PLATFORM_COMMAND_MODULES = {
        'win': ('client.commands.platform.win', 'WindowsCommands'),
        'mac': ('client.commands.platform.mac', 'MacCommands'),
        'linux': ('client.commands.platform.linux', 'LinuxCommands'),
        'ios': ('client.commands.platform.ios', 'iOSCommands')
    }

    def __init__(self, socket):
        self.socket = socket
        self.platform_commands = None
        self.argument_command_registry = None

    def _get_platform_name(self) -> str:
        """
        获取当前系统平台名称
        """
        # return platform.system().lower()
        # return detect_platform_name().lower()
        return get_local_identity().os_alias

    def _load_platform_command_class(self):
        """
        根据当前平台动态加载命令类
        """
        system = self._get_platform_name()
        platform_info = self.PLATFORM_COMMAND_MODULES.get(system)
        if not platform_info:
            raise NotImplementedError(f"Unsupported OS: {system}")

        module_name, class_name = platform_info
        module = __import__(module_name, fromlist=[class_name])
        return getattr(module, class_name)

    def get_commands(self):
        """
        获取当前平台对应的命令实例（懒加载）
        """
        if self.platform_commands is None:
            command_class = self._load_platform_command_class()
            self.platform_commands = command_class(self.socket)
        return self.platform_commands

    def get_argument_command_registry(self):
        """
        获取当前平台对应的 acmd 注册表（懒加载）
        """
        if self.argument_command_registry is None:
            self.argument_command_registry = ArgumentCommandRegistry(self.get_commands())
        return self.argument_command_registry








