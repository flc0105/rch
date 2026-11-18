"""Compose Shell and ACMD registries into the existing execution host.

The runtime binds one execution context to the host. Command registrations
remain independent in client.commands.shell and client.commands.acmd.
"""

from client.commands.acmd.commands import DesktopACMDCommands
from client.commands.acmd.platform.ios import iOSACMDCommands
from client.commands.acmd.platform.mac import MacACMDCommands
from client.commands.shell.base import CommandBase
from client.commands.shell.commands import ShellCommands
from client.commands.shell.platform.ios import iOSShellCommands
from client.commands.shell.platform.linux import LinuxShellCommands
from client.commands.shell.platform.mac import MacShellCommands
from client.commands.shell.platform.win import WindowsShellCommands


class MacCommands(MacShellCommands, MacACMDCommands, ShellCommands,
                  DesktopACMDCommands, CommandBase):
    command_platform = 'mac'


class WindowsCommands(WindowsShellCommands, ShellCommands,
                      DesktopACMDCommands, CommandBase):
    command_platform = 'win'


class LinuxCommands(LinuxShellCommands, ShellCommands,
                    DesktopACMDCommands, CommandBase):
    command_platform = 'linux'


class iOSCommands(iOSShellCommands, iOSACMDCommands, ShellCommands, CommandBase):
    command_platform = 'ios'
