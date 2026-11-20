"""Register the shared Client maintenance commands."""

from client.commands.shell.standalone.clean import clean as clean_command
from client.commands.shell.standalone.update import update as update_command


class ShellMaintenanceCommands:
    clean = clean_command
    update = update_command
