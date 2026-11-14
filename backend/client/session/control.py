"""Independent Client session lifecycle actions."""
import os

from core.protocol.control import SessionAction


class SessionControl:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, scope, action, payload):
        if action != SessionAction.DISCONNECT:
            return 0, 'Unsupported session Control action'
        scope._checkpoint()
        # This operation intentionally ends the process, like kill_instance.
        # The Server has already recorded the disconnect intent before sending.
        try:
            self.connection.report_session_end('server_requested_disconnect', command='kill_instance')
        finally:
            self.connection.close()
            os._exit(0)
