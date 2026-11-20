"""Platform command ownership, Shell reflection, and explicit ACMD registration."""

import inspect
from importlib import import_module
from types import MethodType

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.runtime.context import ClientCommandContext
from client.commands.runtime.manifest_metadata import command_metadata
from client.commands.shell.decorators import supports_shell_platform
from core.device.local_identity import get_local_identity


class CommandCatalog:
    """Resolve owner modules for the local Client, without composing command classes."""

    SHELL_COMMON_MODULES = (
        'client.commands.shell.common.execution',
        'client.commands.shell.common.session',
        'client.commands.shell.common.system',
        'client.commands.shell.common.maintenance',
        'client.commands.shell.common.media',
    )
    SHELL_PLATFORM_MODULES = {
        'mac': 'client.commands.shell.platform.mac',
        'win': 'client.commands.shell.platform.win',
        'ios': 'client.commands.shell.platform.ios',
        'linux': None,
    }
    ACMD_COMMON_MODULES = (
        'client.commands.acmd.common.network',
        'client.commands.acmd.common.files',
        'client.commands.acmd.common.inspection',
        'client.commands.acmd.common.interaction',
        'client.commands.acmd.common.process',
    )
    ACMD_PLATFORM_MODULES = {
        'mac': 'client.commands.acmd.platform.mac',
        'win': None,
        'ios': 'client.commands.acmd.platform.ios',
        'linux': None,
    }

    def __init__(self, socket):
        self.socket = socket
        self.command_context = None
        self.argument_command_registry = None
        self._shell_commands = None

    def _get_platform_name(self):
        return get_local_identity().os_alias

    def _owner_modules(self, common, platform_modules):
        platform = self._get_platform_name()
        if platform not in platform_modules:
            raise NotImplementedError(f'Unsupported OS: {platform}')
        names = (*common, *((platform_modules[platform],) if platform_modules[platform] else ()))
        return (import_module(name) for name in names)

    def get_commands(self):
        """Return runtime capabilities, not a dynamically assembled command host."""
        if self.command_context is None:
            self.command_context = ClientCommandContext(self.socket, self._get_platform_name())
        return self.command_context

    def _collect_shell_commands(self):
        """Discover exports on Common/Platform modules; Standalone is not scanned."""
        result = {}
        context = self.get_commands()
        for module in self._owner_modules(self.SHELL_COMMON_MODULES, self.SHELL_PLATFORM_MODULES):
            for name, func in inspect.getmembers(module, inspect.isfunction):
                if not hasattr(func, 'help') or name != func.__name__:
                    continue
                if name in result:
                    raise ValueError(f'Duplicate Shell command: {name}')
                result[name] = MethodType(func, context)
        return result

    def get_shell_command(self, name):
        if self._shell_commands is None:
            self._shell_commands = self._collect_shell_commands()
        return self._shell_commands.get(name)

    def get_exported_shell_commands(self):
        if self._shell_commands is None:
            self._shell_commands = self._collect_shell_commands()
        platform = self._get_platform_name()
        return {name: handler for name, handler in self._shell_commands.items()
                if supports_shell_platform(handler, platform)}

    def get_argument_command_registry(self):
        if self.argument_command_registry is None:
            context = self.get_commands()
            registry = ArgumentCommandRegistry(context)
            for module in self._owner_modules(self.ACMD_COMMON_MODULES, self.ACMD_PLATFORM_MODULES):
                module.register_commands(registry)
            self.argument_command_registry = registry
        return self.argument_command_registry

    def get_command_manifest_payload(self):
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
