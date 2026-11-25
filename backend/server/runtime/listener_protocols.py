"""Registered Server listener protocols and build capabilities."""

from core.agent_build_contract import AgentBuilderKind


class TcpListenerProtocol:
    name = 'tcp'
    label = 'TCP'
    build_label = 'TCP'
    supported_builders = None
    notice = ''
    builder_warning = ''

    def create_listener(self, server, config, identity_store):
        from server.runtime.server_listener import ServerListener
        return ServerListener(server, config=config)

    def validate_build(self, builder):
        if self.supported_builders is not None and builder not in self.supported_builders:
            raise ValueError(f'{self.label} does not support builder: {builder}')

    def describe(self):
        return {
            'id': self.name, 'label': self.label, 'build_label': self.build_label,
            'supported_builders': list(self.supported_builders) if self.supported_builders is not None else None,
            'notice': self.notice, 'builder_warning': self.builder_warning,
        }


class MtlsTcpListenerProtocol(TcpListenerProtocol):
    name = 'mtls_tcp'
    label = 'mTLS/TCP'
    build_label = 'mTLS/TCP'
    notice = 'Initialize Server identity and provision the Client identity before connecting.'
    builder_warning = 'mTLS requires installed Client Identity files.'

    def create_listener(self, server, config, identity_store):
        from server.runtime.server_listener import ServerListener
        return ServerListener(server, config=config,
                              ssl_context=identity_store.context(server_side=True),
                              verify_peer=identity_store.verify_client)


_LISTENER_PROTOCOLS = {}


def register_listener_protocol(protocol):
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
register_listener_protocol(MtlsTcpListenerProtocol())
