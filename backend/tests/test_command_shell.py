import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server.runtime.command_shell import ServerCommandShell, _ConsoleInputUnavailable


class CommandShellTests(unittest.TestCase):
    def test_unavailable_console_does_not_retry(self):
        shell = ServerCommandShell.__new__(ServerCommandShell)
        shell.server = SimpleNamespace(socket=Mock())
        shell._read_console_input = Mock(side_effect=_ConsoleInputUnavailable('stdin unavailable'))
        shell._wait_without_console = Mock()
        shell._handle_console_command = Mock()

        with patch('server.runtime.command_shell.write'), patch('builtins.print'):
            shell.serve_console_loop()

        shell._read_console_input.assert_called_once_with('server> ')
        shell._wait_without_console.assert_called_once_with()
        shell._handle_console_command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
