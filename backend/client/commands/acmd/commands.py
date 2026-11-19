"""Shared desktop ACMD registrations."""

from client.commands.acmd.common.network import ACMDNetworkCommands
from client.commands.acmd.common.files import ACMDArchiveCommands
from client.commands.acmd.common.process import ACMDProcessCommands


class DesktopACMDCommands(ACMDProcessCommands, ACMDNetworkCommands, ACMDArchiveCommands):
    """ACMD commands available on macOS, Windows and Linux."""
