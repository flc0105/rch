"""macOS-only structured command registrations."""
from client.commands.acmd.standalone.launchd import launchd as launchd_command


class MacACMDCommands:
    launchd = launchd_command
