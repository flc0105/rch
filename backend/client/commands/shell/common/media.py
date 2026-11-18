"""Shared media Shell command registrations."""

from client.commands.shell.standalone.screenshot import screenshot as screenshot_command


class ShellMediaCommands:
    """Media commands shared by supported platforms."""

    screenshot = screenshot_command
