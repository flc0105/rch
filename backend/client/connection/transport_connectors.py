"""Python Agent connection strategies selected by configured transport name."""
import hashlib
import hmac
import ssl


class TcpConnector:
    name = 'tcp'

    def validate(self, config):
        pass

    def connect(self, server, address, config):
        return server.connect(address)


class PinnedTlsConnector(TcpConnector):
    name = 'tls_tcp'

    def validate(self, config):
        fingerprint = str(config.get('server_tls_fingerprint') or '').lower().strip()
        if len(fingerprint) != 64 or any(c not in '0123456789abcdef' for c in fingerprint):
            raise ValueError('Invalid TLS certificate fingerprint')

    def connect(self, server, address, config):
        if not server.connect(address):
            return False
        # Only the certificate fingerprint is provisioned in the Bundle.
        # Verify the peer before sending RCH info or commands.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        wrapped = context.wrap_socket(server.socket, server_hostname=address[0])
        actual = hashlib.sha256(wrapped.getpeercert(binary_form=True)).hexdigest()
        expected = str(config.get('server_tls_fingerprint') or '').lower().strip()
        if not hmac.compare_digest(actual, expected):
            wrapped.close()
            raise ssl.SSLError('TLS server certificate fingerprint mismatch')
        server.socket = wrapped
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
register_connector(PinnedTlsConnector())
