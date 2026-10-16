from client.commands.arguments.decorators import argument_command
from client.commands.common.commands import CommonCommands
from client.commands.platform.specs.common import NETSTAT_ARGUMENT_SPEC, PS_ARGUMENT_SPEC


class LinuxCommands(CommonCommands):

    def __init__(self, socket):
        super().__init__(socket)

    @argument_command('netstat', spec=NETSTAT_ARGUMENT_SPEC)
    def _acmd_netstat(self, args_dict, payload=None):
        return self._acmd_netstat_common(args_dict, payload)

    @argument_command('ps', spec=PS_ARGUMENT_SPEC)
    def _acmd_ps(self, args_dict, payload=None):
        return self._acmd_ps_common(args_dict, payload)