"""Common and desktop ACMD registrations."""
from client.commands.acmd.common.files import ACMDFileCommands
from client.commands.acmd.common.inspection import ACMDInspectionCommands
from client.commands.acmd.common.interaction import ACMDInteractionCommands
from client.commands.acmd.common.network import ACMDNetworkCommands
from client.commands.acmd.common.process import ACMDProcessCommands


class CommonACMDCommands(ACMDNetworkCommands, ACMDFileCommands, ACMDInspectionCommands, ACMDInteractionCommands):
    """Shared registrations, filtered by the Registry for each platform."""


class DesktopACMDCommands(ACMDProcessCommands, CommonACMDCommands):
    """Compose desktop process commands with the shared registrations."""
