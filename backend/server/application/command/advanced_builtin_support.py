"""New opt-in, preview-gated builtins; ordinary Client process commands remain intact."""
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
        # Let the output event flush before transport teardown.
        worker = threading.Timer(0.35, self.conn.close)
        worker.daemon = True
        worker.start()

    def advanced_demo(self, arg=''):
        if str(arg or '').strip():
            yield 0, 'Usage: interaction_advanced_demo'
            return
        try:
            choice = self.interactions.select('Choose a harmless demo action:',
                                               ['Preview only', 'Execute demo'], title='Select demo mode')
            if choice == 'Preview only':
                yield 1, 'Demo preview only; no operation executed.'
                return
            secret = self.interactions.ask('Enter a secret sample (never printed):',
                                           title='Secret input demo', secret=True)
            if not self.interactions.confirm('Run harmless demo and discard secret?', title='Demo approval'):
                yield 0, 'Demo rejected'
                return
            yield 1, 'Demo complete; secret received but not disclosed.'
        except BuiltinInteractionError as exc:
            yield 0, f'Demo cancelled: {exc}'

