"""Native Client interaction registrations."""
from client.commands.acmd.standalone.msgbox import msgbox as msgbox_command
from client.commands.acmd.standalone.notify import notify as notify_command


class ACMDInteractionCommands:
    msgbox = msgbox_command
    notify = notify_command
