"""Server-side command interaction support."""

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
        # Keep the Web task active while Client @confirm requests its own approval.
        # The normal command channel binds command_id and interaction grant.
        for status, result in self.conn.send_command('kill_connection'):
            if result is None:
                # The Client closes its socket after approving kill_connection;
                # Server's connection listener wakes the waiting command with EOF.
                yield 1, 'Client connection closed.'
                return
            yield status, result

