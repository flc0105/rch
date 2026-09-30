import errno
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server.runtime.server_listener import ServerListener


class ServerListenerTests(unittest.TestCase):
    def test_stop_marks_listener_and_closes_socket(self):
        server = SimpleNamespace(socket=Mock())
        listener = ServerListener(server)

        listener.stop()

        self.assertTrue(listener._stop_event.is_set())
        server.socket.shutdown.assert_called_once_with()
        server.socket.close.assert_called_once_with()

    def test_shutdown_socket_error_ends_accept_loop_without_logging(self):
        server = SimpleNamespace(socket=Mock())
        listener = ServerListener(server)
        listener._bind_server_socket = Mock()

        def fail_after_stop():
            listener._stop_event.set()
            raise OSError(errno.EBADF, 'Bad file descriptor')

        listener._accept_connection = Mock(side_effect=fail_after_stop)

        with patch('server.runtime.server_listener.logger.error') as log_error:
            listener.serve()

        listener._accept_connection.assert_called_once_with()
        log_error.assert_not_called()

    def test_closed_socket_errno_ends_accept_loop_even_without_stop_flag(self):
        server = SimpleNamespace(socket=Mock())
        listener = ServerListener(server)
        listener._bind_server_socket = Mock()
        listener._accept_connection = Mock(side_effect=OSError(errno.EBADF, 'Bad file descriptor'))

        with patch('server.runtime.server_listener.logger.error') as log_error:
            listener.serve()

        listener._accept_connection.assert_called_once_with()
        log_error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
