from client.commands.arguments.decorators import argument_command
from client.commands.common.commands import CommonCommands
from client.commands.platform.specs.common import NETSTAT_ARGUMENT_SPEC, PS_ARGUMENT_SPEC
from client.commands.platform.services.linux.system_service import LinuxSystemService
from core.utils.decorator import desc


class LinuxCommands(CommonCommands):

    def __init__(self, socket):
        super().__init__(socket)
        self.linux_system = LinuxSystemService(self)

    @desc('Get Linux system information', group='system')
    def getinfo(self, arg=''):
        if str(arg or '').strip() not in ('', '--json', 'json'):
            return 0, 'Usage: getinfo [--json]'
        return self.linux_system.collect_system_info()

    @argument_command('netstat', spec=NETSTAT_ARGUMENT_SPEC)
    def _acmd_netstat(self, args_dict, payload=None):
        return self._acmd_netstat_common(args_dict, payload)

    @argument_command('ps', spec=PS_ARGUMENT_SPEC)
    def _acmd_ps(self, args_dict, payload=None):
        return self._acmd_ps_common(args_dict, payload)