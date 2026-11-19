"""Common ACMD archive registrations."""

from client.commands.acmd.standalone.zip import zip as zip_command
from client.commands.acmd.standalone.unzip import unzip as unzip_command


class ACMDArchiveCommands:
    zip = zip_command
    unzip = unzip_command
