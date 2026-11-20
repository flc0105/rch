"""Common Shell command registrations, grouped by responsibility."""

from client.commands.shell.common.execution import ShellExecutionCommands
from client.commands.shell.common.maintenance import ShellMaintenanceCommands
from client.commands.shell.common.media import ShellMediaCommands
from client.commands.shell.common.session import ShellSessionCommands
from client.commands.shell.common.system import ShellSystemCommands


class ShellCommands(
    ShellExecutionCommands,
    ShellSessionCommands,
    ShellSystemCommands,
    ShellMaintenanceCommands,
    ShellMediaCommands,
):
    """Shell command groups. Methods are registered on the platform host."""
