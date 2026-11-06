"""Registered Server listener protocols: endpoint creation and Agent build settings.

Each protocol owns its transport-specific setup. ListenerManager stays responsible
for configuration and lifecycle, not for inspecting individual protocol names.
"""
import hashlib
import os
import ssl
import subprocess


class TcpListenerProtocol:
    name = 'tcp'
    label = 'TCP'
    build_label = 'TCP'
    supported_builders = None  # All registered builders can target plain TCP.
    notice = ''
    builder_warning = ''

    def create_listener(self, server, config, cert_dir):
        from server.runtime.server_listener import ServerListener
        return ServerListener(server, config=config)

    def certificate_fingerprint(self, listener_id, cert_dir):
        return ''

    def validate_build(self, builder, fingerprint):
        if self.supported_builders is not None and builder not in self.supported_builders:
            raise ValueError(f'{self.label} does not support builder: {builder}')

    def build_fingerprint(self, listener_id, builder, cert_dir):
        self.validate_build(builder, '')
        return ''

    def describe(self):
        return {
            'id': self.name,
            'label': self.label,
            'build_label': self.build_label,
            'supported_builders': list(self.supported_builders) if self.supported_builders is not None else None,
            'notice': self.notice,
            'builder_warning': self.builder_warning,
        }


class TlsTcpListenerProtocol(TcpListenerProtocol):
    name = 'tls_tcp'
    label = 'TLS/TCP'
    build_label = 'TLS/TCP (pinned certificate)'
    supported_builders = ('bundle', 'go', 'go_loader')
    notice = 'A self-signed certificate is generated once. Bundle and Go clients pin its fingerprint.'
    builder_warning = 'TLS/TCP supports Bundle, Go (Simple), and Go (Loader)'

    @staticmethod
    def _certificate_paths(listener_id, cert_dir):
        return (os.path.join(cert_dir, listener_id + '.crt'),
                os.path.join(cert_dir, listener_id + '.key'))

    def _ensure_certificate(self, listener_id, cert_dir):
        cert, key = self._certificate_paths(listener_id, cert_dir)
        if os.path.isfile(cert) and os.path.isfile(key):
            return cert, key
        if os.path.exists(cert) != os.path.exists(key):
            raise RuntimeError('TLS certificate and key must both exist')
        os.makedirs(cert_dir, mode=0o700, exist_ok=True)
        # OpenSSL is only needed when first creating a TLS listener.
        result = subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                                 '-sha256', '-nodes', '-days', '3650',
                                 '-subj', '/CN=RCH Listener ' + listener_id,
                                 '-keyout', key, '-out', cert], capture_output=True, text=True)
        if result.returncode:
            for path in (key, cert):
                if os.path.exists(path):
                    os.remove(path)
            raise RuntimeError('Failed to create TLS certificate: ' + result.stderr[-400:])
        os.chmod(key, 0o600)
        return cert, key

    def create_listener(self, server, config, cert_dir):
        cert, key = self._ensure_certificate(config['id'], cert_dir)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        from server.runtime.server_listener import ServerListener
        return ServerListener(server, config=config, ssl_context=context)

    def certificate_fingerprint(self, listener_id, cert_dir):
        cert, _ = self._ensure_certificate(listener_id, cert_dir)
        with open(cert, encoding='ascii') as f:
            pem = f.read()
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()

    def validate_build(self, builder, fingerprint):
        if builder not in self.supported_builders or len(fingerprint) != 64:
            raise ValueError('TLS/TCP requires a compatible builder and a pinned server certificate')

    def build_fingerprint(self, listener_id, builder, cert_dir):
        if builder not in self.supported_builders:
            raise ValueError('TLS/TCP supports Bundle, Go (Simple), and Go (Loader)')
        fingerprint = self.certificate_fingerprint(listener_id, cert_dir)
        self.validate_build(builder, fingerprint)
        return fingerprint


_LISTENER_PROTOCOLS = {}


def register_listener_protocol(protocol):
    """Register one implementation; adding protocols does not modify ListenerManager."""
    if not protocol.name or protocol.name in _LISTENER_PROTOCOLS:
        raise ValueError('Invalid or duplicate listener protocol')
    _LISTENER_PROTOCOLS[protocol.name] = protocol


def get_listener_protocol(name):
    try:
        return _LISTENER_PROTOCOLS[name]
    except (KeyError, TypeError):
        raise ValueError('Unsupported listener protocol: ' + str(name)) from None


def list_listener_protocols():
    return [protocol.describe() for protocol in _LISTENER_PROTOCOLS.values()]


register_listener_protocol(TcpListenerProtocol())
register_listener_protocol(TlsTcpListenerProtocol())
