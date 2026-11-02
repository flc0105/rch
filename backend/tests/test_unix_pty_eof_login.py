"""Regression coverage for Unix PTY shell startup and normal master EOF."""

import os
import threading
import unittest

from client.pty.backends.unix_pty_backend import UnixPtyBackend


class FakePtyManager:
    def __init__(self):
        self.session = None
        self.output = bytearray()
        self.errors = []
        self.closed = threading.Event()
        self.exit_code = None

    def register_session(self, session):
        self.session = session

    def get_session(self, session_id):
        return self.session

    def send_opened(self, session_id, shell=''):
        pass

    def send_error(self, session_id, message):
        self.errors.append(message)

    def send_output(self, session_id, data):
        self.output.extend(data)

    def finalize_session(self, session_id, exit_code=0):
        self.exit_code = exit_code
        if self.session is not None:
            self.session.backend.cleanup_session(self.session)
        self.session = None
        self.closed.set()


class UnixPtyEofTests(unittest.TestCase):
    def test_interactive_login_shell_args_for_bash_and_zsh(self):
        self.assertEqual(UnixPtyBackend.shell_arguments('/bin/bash'),
                         ['/bin/bash', '-l', '-i'])
        self.assertEqual(UnixPtyBackend.shell_arguments('/bin/zsh'),
                         ['/bin/zsh', '-l', '-i'])
        self.assertEqual(UnixPtyBackend.shell_arguments('/bin/sh'),
                         ['/bin/sh', '-i'])

    @unittest.skipUnless(os.name == 'posix' and os.path.isfile('/bin/bash'),
                         'Requires a real Unix PTY and bash')
    def test_real_shell_exit_is_clean_and_preserves_final_output(self):
        manager = FakePtyManager()
        backend = UnixPtyBackend(manager)
        backend.open_session('pty-real-eof', shell='/bin/bash', cols=65, rows=20)
        self.assertIsNotNone(manager.session)
        # Drain after child exits: even if waitpid observes termination first,
        # output already queued in the master must reach the operator terminal.
        os.write(manager.session.master_fd, b"printf '%010000dFINAL_OUTPUT\\n' 0; exit 7\n")
        self.assertTrue(manager.closed.wait(8), 'PTY reader did not close after shell exit')
        self.assertEqual(manager.errors, [], manager.errors)
        self.assertIn(b'0' * 10000 + b'FINAL_OUTPUT', manager.output)
        self.assertEqual(manager.exit_code, 7)


if __name__ == '__main__':
    unittest.main()
