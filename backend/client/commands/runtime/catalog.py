import inspect

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.runtime.manifest_metadata import command_metadata
from client.commands.shell.decorators import supports_shell_platform
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
    #     'windows': ('client.commands.runtime.hosts', 'WindowsCommands'),
    #     'darwin': ('client.commands.runtime.hosts', 'MacCommands'),
    #     'linux': ('client.commands.runtime.hosts', 'LinuxCommands'),
    #     'ios': ('client.commands.runtime.hosts', 'iOSCommands')
    # }
    PLATFORM_COMMAND_MODULES = {
        'win': ('client.commands.runtime.hosts', 'WindowsCommands'),
        'mac': ('client.commands.runtime.hosts', 'MacCommands'),
        'linux': ('client.commands.runtime.hosts', 'LinuxCommands'),
        'ios': ('client.commands.runtime.hosts', 'iOSCommands')
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









    def get_exported_shell_commands(self):
        """Collect Shell handlers for the current Client platform."""
        instance = self.get_commands()
        platform = self._get_platform_name()
        return {
            name: method
            for name, method in inspect.getmembers(
                instance, lambda value: inspect.ismethod(value) or inspect.isfunction(value)
            )
            if hasattr(method, 'help') and supports_shell_platform(method, platform)
        }

    def get_command_manifest_payload(self):
        """Provide the handshake manifest for Shell and ACMD commands."""
        platform = self._get_platform_name()
        payload = [
            {
                'name': name,
                'help': method.help,
                'group': getattr(method, 'group', 'general'),
                'suggest': getattr(method, 'suggest', True),
                **command_metadata(method, platform=platform),
            }
            for name, method in self.get_exported_shell_commands().items()
            if getattr(method, 'suggest', True)
        ]
        payload.extend(self.get_argument_command_registry().get_manifest_payload())
        payload.sort(key=lambda item: (item.get('group', 'general'), item.get('name', '').lower()))
        return payload
