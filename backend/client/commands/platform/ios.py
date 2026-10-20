from client.commands.arguments.decorators import argument_command
from client.commands.common.commands import CommonCommands
from client.commands.runtime.interrupts import timeout
from client.commands.platform.services.ios.console_service import iOSConsoleService
from client.commands.platform.services.ios.file_system_service import iOSFileSystemService
from client.commands.platform.services.ios.network_service import iOSNetworkService
from client.commands.platform.services.ios.system_service import iOSSystemService
from client.commands.platform.specs.ios import *
from client.commands.platform.specs.common import PS_ARGUMENT_SPEC
from core.utils.decorator import desc


class iOSCommands(CommonCommands):
    """iOS / Pythonista 平台专用命令集合"""

    def __init__(self, socket):
        super().__init__(socket)
        self.ios_file_system = iOSFileSystemService(self)
        self.ios_system = iOSSystemService(self)
        self.ios_console = iOSConsoleService(self)
        self.ios_network = iOSNetworkService(self)

    # ------------------ 基础 shell ------------------ #

    @desc('List directory contents', group='shell')
    def ls(self, path='.'):
        return self.ios_file_system.list_directory(path)

    @desc('Show current username', group='shell')
    def whoami(self):
        return self.ios_system.get_username()

    @desc('Create empty file', group='shell')
    def touch(self, path):
        return self.ios_file_system.touch(path)

    @desc('Create directory', group='shell')
    def mkdir(self, path):
        return self.ios_file_system.mkdir(path)

    @desc('Remove file', group='shell')
    def rm(self, path):
        return self.ios_file_system.rm(path)

    @desc('Remove directory recursively', group='shell')
    def rmdir(self, path):
        return self.ios_file_system.rmdir(path)

    @desc('Read text file', group='shell')
    def cat(self, path):
        return self.ios_file_system.cat(path)

    @desc('Compute file MD5', group='shell')
    def md5sum(self, path=''):
        return self.ios_file_system.md5sum(path)

    @desc('Print environment variables', group='shell')
    def printenv(self, name=''):
        return self.ios_file_system.printenv(name)

    @desc('Echo text or expand environment variables', group='shell')
    def echo(self, text=''):
        return self.ios_file_system.echo(text)

    # ------------------ 系统信息 ------------------ #

    @desc('Get system information', group='platform')
    @timeout(20)
    def getinfo(self):
        return self.ios_system.collect_info()

    # ------------------ 剪贴板 ------------------ #

    @desc('Read clipboard text', group='mobile')
    def readclip(self):
        return self.ios_console.read_clipboard()

    @desc('Write clipboard text', group='mobile')
    def writeclip(self, text=''):
        return self.ios_console.write_clipboard(text)

    # ------------------ 手机常用 ------------------ #

    @desc('Open URL', group='console')
    def openurl(self, url):
        return self.ios_console.open_url(url)

    @desc('Clear console output', group='console')
    def clearconsole(self):
        return self.ios_console.clear_console()

    @desc('QuickLook preview file', group='console')
    def quicklook(self, path):
        return self.ios_console.quick_look(path)

    @desc('Open file in other app', group='console')
    def openin(self, path):
        return self.ios_console.open_in(path)

    @desc('Get current location', group='mobile')
    @timeout(15)
    def getlocation(self):
        return self.ios_console.get_location()

    @desc('Speak text', group='mobile')
    def speak(self, text=''):
        return self.ios_console.speak(text)

    @desc('List contacts via CNContactStore', group='mobile')
    def listcontacts(self):
        return self.ios_system.list_contacts()

    @desc('Pick photo or file and upload', group='console')
    def pickupload(self, kind='photo'):
        return self.ios_console.pick_upload(kind)

    @desc('Keep screen awake', group='console')
    def keepawake(self, arg):
        return self.ios_console.keepawake(arg)

    @desc('Force quit app', group='console')
    def killapp(self):
        return self.ios_console.killapp()

    @argument_command('alert', spec=ALERT_ARGUMENT_SPEC)
    def alert(self, args_dict, payload=None):
        return self.ios_console.acmd_alert(args_dict)

    @argument_command('notify', spec=NOTIFY_ARGUMENT_SPEC)
    def notify(self, args_dict, payload=None):
        return self.ios_console.acmd_notify(args_dict)

    @argument_command('find', spec=FIND_ARGUMENT_SPEC)
    def find(self, args_dict, payload=None):
        return self.ios_file_system.acmd_find(args_dict)

    @argument_command('tree', spec=TREE_ARGUMENT_SPEC)
    def tree(self, args_dict, payload=None):
        return self.ios_file_system.acmd_tree(args_dict)

    @argument_command('head', spec=HEAD_ARGUMENT_SPEC)
    def head(self, args_dict, payload=None):
        return self.ios_file_system.acmd_head(args_dict)

    @argument_command('tail', spec=TAIL_ARGUMENT_SPEC)
    def tail(self, args_dict, payload=None):
        return self.ios_file_system.acmd_tail(args_dict)

    @argument_command('wget', spec=WGET_ARGUMENT_SPEC)
    def wget(self, args_dict, payload=None):
        return self.ios_file_system.acmd_wget(args_dict)

    @argument_command('tcp_ping', spec=TCP_PING_ARGUMENT_SPEC)
    def tcp_ping(self, args_dict, payload=None):
        return self.ios_network.acmd_tcp_ping(args_dict)

    @argument_command('ping', spec=PING_ARGUMENT_SPEC)
    def ping(self, args_dict, payload=None):
        return self.ios_network.acmd_ping(args_dict)

    @argument_command('ps', spec=PS_ARGUMENT_SPEC)
    def _acmd_ps(self, args_dict, payload=None):
        return self._acmd_ps_common(args_dict, payload)
