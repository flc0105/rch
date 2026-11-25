"""Python Client connection strategies selected by configured transport name."""
from client.connection.mtls import create_context


class TcpConnector:
    name = 'tcp'

    def validate(self, config):
        pass

    def connect(self, server, address, config):
        return server.connect(address)


class MtlsConnector(TcpConnector):
    name = 'mtls_tcp'

    def validate(self, config):
        create_context(config, server_side=False)

    def connect(self, server, address, config):
        # Never send any application bytes until mutual certificate validation.
        context = create_context(config, server_side=False)
        if not server.connect(address):
            return False
        try:
            server.socket = context.wrap_socket(server.socket, server_hostname=None)
        except Exception:
            server.socket.close()
            raise
        return True


_CONNECTORS = {}


def register_connector(connector):
    if not connector.name or connector.name in _CONNECTORS:
        raise ValueError('Invalid or duplicate Agent connector')
    _CONNECTORS[connector.name] = connector


def get_connector(name):
    try:
        return _CONNECTORS[name]
    except (KeyError, TypeError):
        raise ValueError('Unknown server transport') from None


register_connector(TcpConnector())
register_connector(MtlsConnector())
