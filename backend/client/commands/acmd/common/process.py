"""Common ACMD process command registrations."""

from client.commands.acmd.standalone.ps import ps as ps_command
from client.commands.acmd.standalone.kill import kill as kill_command


class ACMDProcessCommands:
    ps = ps_command
    kill = kill_command
