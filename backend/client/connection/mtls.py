"""Client-local identity configuration for Reverse dialing and Bind listening."""
import os
import ssl
import stat

from client.runtime.client_util import get_client_bundle_identity_dir


def identity_directory(config):
    configured = str(config.get('identity_dir') or '').strip()
    if configured and not os.path.isabs(configured):
        raise ValueError('mTLS identity_dir must be an absolute path')
    return os.path.abspath(configured) if configured else get_client_bundle_identity_dir()


def create_context(config, *, server_side):
    root = identity_directory(config)
    files = [os.path.join(root, name) for name in ('client.crt', 'client.key', 'server-ca.crt')]
    for path in files:
        if not os.path.isfile(path):
            raise FileNotFoundError('mTLS identity file missing: ' + path)
    if os.name == 'posix' and os.stat(files[1]).st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError('mTLS private key must not be accessible by group or others')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server_side else ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if not server_side:
        context.check_hostname = False  # Trust the Server CA, not the network endpoint name.
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=files[2])
    context.load_cert_chain(files[0], files[1])
    return context
