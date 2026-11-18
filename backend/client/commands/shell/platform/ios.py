from client.commands.runtime.interrupts import timeout
from client.commands.platform.services.ios.console_service import iOSConsoleService
from client.commands.platform.services.ios.file_system_service import iOSFileSystemService
from client.commands.platform.services.ios.system_service import iOSSystemService
from client.commands.shell.decorators import shell_command


class iOSShellCommands:
    """iOS / Pythonista Shell commands."""
    # Unsupported desktop commands remain unregistered on iOS.
    # Their local overrides retain explicit unavailable errors and prevent Shell export.

    def __init__(self, socket):
        super().__init__(socket)
        self.ios_file_system = iOSFileSystemService(self)
        self.ios_system = iOSSystemService(self)
        self.ios_console = iOSConsoleService(self)

    def shell(self, command=''):
        return 0, 'OS shell execution is unavailable on iOS'

    def shell_stream(self, command=''):
        return self.shell(command)

    def bgrun(self, command=''):
        return self.shell(command)

    def run_detached(self, command=''):
        return self.shell(command)

    def is_elevated(self):
        return 0, 'Privilege elevation is unavailable on iOS'

    def piplist(self, arg=''):
        return 0, 'Package enumeration is unavailable on iOS'

    def keyboard_send(self, text=''):
        return 0, 'System keyboard injection is unavailable on iOS'

    def userenum(self):
        return 0, 'System user enumeration is unavailable on iOS'

    def spawn_instance(self):
        return 0, 'Starting another Client process is unavailable on iOS'

    def relaunch_instance(self, options=''):
        return 0, 'Process relaunch is unavailable on iOS'

    def reexec_instance(self):
        return 0, 'Process replacement is unavailable on iOS'

    @shell_command('List directory contents', group='shell')
    def ls(self, path='.'):
        return self.ios_file_system.list_directory(path)

    @shell_command('Show current username', group='shell')
    def whoami(self):
        return self.ios_system.get_username()

    @shell_command('Create empty file', group='shell')
    def touch(self, path):
        return self.ios_file_system.touch(path)

    @shell_command('Read text file', group='shell')
    def cat(self, path):
        return self.ios_file_system.cat(path)

    @shell_command('Compute file MD5', group='shell')
    def md5sum(self, path=''):
        return self.ios_file_system.md5sum(path)

    @shell_command('Print environment variables', group='shell')
    def printenv(self, name=''):
        return self.ios_file_system.printenv(name)

    @shell_command('Echo text or expand environment variables', group='shell')
    def echo(self, text=''):
        return self.ios_file_system.echo(text)

    @shell_command('Get system information', group='system')
    @timeout(20)
    def getinfo(self):
        return self.ios_system.collect_info()

    @shell_command('Show system uptime', group='system')
    def uptime(self):
        return self.ios_system.get_uptime()

    @shell_command('Read clipboard text', group='device')
    def clipboard_read(self):
        return self.ios_console.read_clipboard()

    @shell_command('Write clipboard text', group='device')
    def clipboard_write(self, text=''):
        return self.ios_console.write_clipboard(text)

    @shell_command('Clear console output', group='console')
    def clear_console(self):
        return self.ios_console.clear_console()

    @shell_command('Get current location', group='device')
    @timeout(15)
    def get_location(self):
        return self.ios_console.get_location()

    @shell_command('Speak text', group='device')
    def speak(self, text=''):
        return self.ios_console.speak(text)

    @shell_command('List contacts via CNContactStore', group='device')
    def list_contacts(self, arg=''):
        if str(arg or '').strip():
            return 0, 'Usage: list_contacts'
        return self.ios_system.list_contacts()

    @shell_command('List reminders', group='device')
    def list_reminders(self, arg=''):
        if str(arg or '').strip():
            return 0, 'Usage: list_reminders'
        return self.ios_system.list_reminders()

    @shell_command('Keep screen awake', group='console')
    def keep_awake(self, arg):
        return self.ios_console.keep_awake(arg)
