"""Terminal connection failures; network EOF and timeouts remain distinct."""
import ssl


class ConnectionConfigurationError(OSError):
    """Local listener or identity configuration could not be loaded."""


class ConnectionAuthenticationError(ConnectionError):
    """An explicit certificate or application admission rejection."""


class ConnectionTLSRejectionError(ConnectionError):
    """A peer explicitly refused TLS; not necessarily a certificate error."""


def terminal_connection_error(error):
    if isinstance(error, (ConnectionConfigurationError, ConnectionAuthenticationError,
                          ConnectionTLSRejectionError)):
        return error
    if isinstance(error, ssl.SSLCertVerificationError):
        return ConnectionAuthenticationError(f'mTLS certificate verification failed: {error}')
    if isinstance(error, ssl.SSLError):
        reason = getattr(error, 'reason', None) or ''
        # OpenSSL reports peer alerts through structured reason codes. An EOF,
        # timeout or socket reset is not evidence of explicit refusal.
        if reason.startswith(('TLSV1_ALERT_', 'SSLV3_ALERT_', 'TLSV13_ALERT_')):
            if reason.endswith(('CLOSE_NOTIFY', 'USER_CANCELLED')):
                return None
            return ConnectionTLSRejectionError(f'mTLS peer rejected connection: {error}')
    return None
