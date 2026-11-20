"""macOS-only structured command registrations."""
from client.commands.acmd.standalone.launchd import launchd




def register_commands(registry):
    """Register declarations owned by this Common / Platform module."""
    registry.register(launchd)
