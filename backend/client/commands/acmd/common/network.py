"""Common ACMD network command registrations."""

from client.commands.acmd.standalone.ifconfig import ifconfig as ifconfig_command
from client.commands.acmd.standalone.netstat import netstat as netstat_command


class ACMDNetworkCommands:
    ifconfig = ifconfig_command
    netstat = netstat_command
