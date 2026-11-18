from client.commands.platform.services.linux.system_service import LinuxSystemService
from client.commands.shell.decorators import shell_command


class LinuxShellCommands:

    def __init__(self, socket):
        super().__init__(socket)
        self.linux_system = LinuxSystemService(self)

    @shell_command('Get Linux system information', group='system')
    def getinfo(self, arg=''):
        if str(arg or '').strip() not in ('', '--json', 'json'):
            return 0, 'Usage: getinfo [--json]'
        return self.linux_system.collect_system_info()
