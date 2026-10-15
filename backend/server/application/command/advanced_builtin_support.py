"""Server-side command interaction support."""
import threading

from server.application.command.interaction_builtin_support import BuiltinInteractionError


class AdvancedBuiltinSupport:
    def __init__(self, conn, interactions):
        self.conn = conn
        self.interactions = interactions

    def disconnect(self, arg=''):
        if str(arg or '').strip():
            yield 0, 'Usage: disconnect'
            return
        info = self.conn.session_info
        identity = (f'Client: {getattr(info, "client_id", "")}\n'
                    f'Host: {getattr(info, "hostname", "")}\n'
                    'Action: close the current Server/Client connection (agent may reconnect).')
        yield 1, 'Preview:\n' + identity
        try:
            if not self.interactions.confirm(identity, title='Disconnect this client?'):
                yield 0, 'Disconnect cancelled'
                return
        except BuiltinInteractionError as exc:
            yield 0, f'Disconnect cancelled: {exc}'
            return
        yield 1, 'Disconnect approved; closing this connection.'
        # Flush the response before dispatching the Client lifecycle command.
        worker = threading.Timer(0.35, lambda: self.conn.send(
            self.conn.command_channel.build_command_payload('kill_connection')))
        worker.daemon = True
        worker.start()

