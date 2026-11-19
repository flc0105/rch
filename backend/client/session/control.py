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
            try:
                # An intentional Server disconnect must stop the process-death
                # supervisor before os._exit; otherwise it respawns this Client.
                recovery_manager = getattr(self.connection, 'process_recovery_watchdog_manager', None)
                try:
                    if recovery_manager is not None:
                        recovery_manager.stop()
                finally:
                    worker_manager = getattr(self.connection, 'watchdog_manager', None)
                    if worker_manager is not None:
                        worker_manager.stop()
            finally:
                try:
                    self.connection.close()
                finally:
                    os._exit(0)
