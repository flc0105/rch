"""Application-local mTLS identity authority, separate from Client releases.

Server and Client identities are issued by different private trust roots so that
presenting a valid Client certificate can never confer the Server's role.
"""
import hashlib
import io
import json
import os
import secrets
import ssl
import subprocess
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone


class IdentityStore:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._lock = threading.RLock()
        self._registry = os.path.join(self.root, 'clients.json')

    def _path(self, filename):
        return os.path.join(self.root, filename)

    @staticmethod
    def _run(*args):
        result = subprocess.run(['openssl', *map(str, args)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('OpenSSL identity operation failed: ' + result.stderr[-400:])
        return result.stdout

    @staticmethod
    def _secure(path, *, directory=False):
        if os.name != 'nt':
            os.chmod(path, 0o700 if directory else 0o600)

    def initialized(self):
        return all(os.path.isfile(self._path(name)) for name in
                   ('server-ca.crt', 'server.crt', 'server.key', 'client-ca.crt', 'client-ca.key', 'clients.json'))

    def require_initialized(self):
        if not self.initialized():
            raise RuntimeError('Initialize mTLS Server identity in Settings > Identities first')

    def initialize(self):
        """Explicit one-time creation; never silently replace existing trust roots."""
        with self._lock:
            if self.initialized():
                return self.status()
            os.makedirs(self.root, mode=0o700, exist_ok=True)
            self._secure(self.root, directory=True)
            if os.listdir(self.root):
                raise RuntimeError('Incomplete mTLS identity directory; repair it before initialization')
            with tempfile.TemporaryDirectory(prefix='.identity-', dir=self.root) as staging:
                for role in ('server', 'client'):
                    key = os.path.join(staging, role + '-ca.key')
                    cert = os.path.join(staging, role + '-ca.crt')
                    self._run('req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-nodes',
                              '-days', '3650', '-subj', '/CN=RCH ' + role + ' trust root',
                              '-addext', 'basicConstraints=critical,CA:TRUE',
                              '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
                              '-keyout', key, '-out', cert)
                self._issue(staging, 'server', 'RCH Server', 365,
                            os.path.join(staging, 'server-ca.crt'),
                            os.path.join(staging, 'server-ca.key'), staging)
                with open(os.path.join(staging, 'clients.json'), 'w', encoding='utf-8') as f:
                    json.dump({}, f)
                for name in os.listdir(staging):
                    source = os.path.join(staging, name)
                    self._secure(source)
                    os.replace(source, self._path(name))
            # Client trust root private key never leaves the Server.
            return self.status()

    def _issue(self, staging, stem, common_name, days, ca_cert, ca_key, destination):
        key = os.path.join(destination, stem + '.key')
        cert = os.path.join(destination, stem + '.crt')
        csr = os.path.join(staging, stem + '.csr')
        ext = os.path.join(staging, stem + '.ext')
        self._run('req', '-new', '-newkey', 'rsa:2048', '-sha256', '-nodes',
                  '-subj', '/CN=' + common_name, '-keyout', key, '-out', csr)
        with open(ext, 'w', encoding='ascii') as f:
            f.write('basicConstraints=critical,CA:FALSE\n'
                    'keyUsage=critical,digitalSignature,keyEncipherment\n'
                    'extendedKeyUsage=serverAuth,clientAuth\n')
        self._run('x509', '-req', '-in', csr, '-CA', ca_cert, '-CAkey', ca_key,
                  '-set_serial', str(secrets.randbits(128)), '-days', str(days),
                  '-sha256', '-extfile', ext, '-out', cert)
        self._secure(key)
        self._secure(cert)
        return cert, key

    @staticmethod
    def _fingerprint(pem):
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()

    def _read(self):
        self.require_initialized()
        with open(self._registry, encoding='utf-8') as f:
            records = json.load(f)
        if not isinstance(records, dict):
            raise ValueError('Invalid Client identity registry')
        return records

    def _save(self, records):
        fd, path = tempfile.mkstemp(prefix='.clients-', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            self._secure(path)
            os.replace(path, self._registry)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def status(self):
        with self._lock:
            if not self.initialized():
                return {'initialized': False, 'clients': []}
            records = self._read()
            return {'initialized': True, 'clients': [
                {k: v for k, v in record.items() if k not in ('fingerprint',)}
                for record in records.values()
            ]}

    def create_client(self, name, days=365):
        name = str(name or '').strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Identity name required (max 80 characters)')
        if type(days) is not int or not 1 <= days <= 825:
            raise ValueError('Certificate validity must be 1–825 days')
        with self._lock:
            records = self._read()
            identity_id = uuid.uuid4().hex
            # Signed certificate identity is immutable; issuance does not depend on an online device.
            with tempfile.TemporaryDirectory(prefix='.client-', dir=self.root) as staging:
                cert, key = self._issue(staging, 'client', 'RCH Client ' + identity_id,
                                        days, self._path('client-ca.crt'),
                                        self._path('client-ca.key'), staging)
                with open(cert, encoding='ascii') as f:
                    fingerprint = self._fingerprint(f.read())
                folder = self._path('client-' + identity_id)
                os.mkdir(folder, mode=0o700)
                self._secure(folder, directory=True)
                for src, dst in ((cert, 'client.crt'), (key, 'client.key')):
                    os.replace(src, os.path.join(folder, dst))
            records[identity_id] = {
                'id': identity_id, 'name': name, 'valid_days': days,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'expires_at': self._enddate(os.path.join(folder, 'client.crt')),
                'revoked': False, 'fingerprint': fingerprint,
            }
            self._save(records)
            return {k: v for k, v in records[identity_id].items() if k != 'fingerprint'}

    def _enddate(self, cert):
        result = self._run('x509', '-in', cert, '-noout', '-enddate').strip().split('=', 1)[1]
        return datetime.strptime(result, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc).isoformat()

    def revoke(self, identity_id):
        with self._lock:
            records = self._read()
            if identity_id not in records:
                raise ValueError('Unknown Client identity')
            records[identity_id]['revoked'] = True
            self._save(records)
            return {k: v for k, v in records[identity_id].items() if k != 'fingerprint'}

    def download(self, identity_id):
        with self._lock:
            records = self._read()
            if identity_id not in records or records[identity_id]['revoked']:
                raise ValueError('Unknown or revoked Client identity')
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as bundle:
                folder = self._path('client-' + identity_id)
                for name in ('client.crt', 'client.key'):
                    with open(os.path.join(folder, name), 'rb') as f:
                        bundle.writestr(name, f.read())
                with open(self._path('server-ca.crt'), 'rb') as f:
                    bundle.writestr('server-ca.crt', f.read())
            buffer.seek(0)
            return buffer

    def verify_client(self, peer_certificate):
        if not peer_certificate:
            raise ssl.SSLError('Missing Client mTLS certificate')
        digest = hashlib.sha256(peer_certificate).hexdigest()
        with self._lock:
            records = self._read()
            if not any(not row['revoked'] and secrets.compare_digest(row['fingerprint'], digest)
                       and datetime.fromisoformat(row['expires_at']) > datetime.now(timezone.utc)
                       for row in records.values()):
                raise ssl.SSLError('Client mTLS identity not authorized or revoked')

    def wrap_outbound_socket(self, sock):
        """Authenticate a Server-initiated Bind/data/tunnel connection."""
        wrapped = None
        try:
            wrapped = self.context(server_side=False).wrap_socket(sock, server_hostname=None)
            self.verify_client(wrapped.getpeercert(binary_form=True))
            # The connection timeout is for dialing/handshake, not for idle sessions.
            wrapped.settimeout(None)
            return wrapped
        except Exception:
            (wrapped or sock).close()
            raise

    def context(self, *, server_side):
        """The Server always presents its own role identity in either TCP direction."""
        with self._lock:
            self.require_initialized()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server_side else ssl.PROTOCOL_TLS_CLIENT)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            if not server_side:
                # Identity trust, not a DNS/hostname binding: endpoints can be forwarded.
                ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_verify_locations(cafile=self._path('client-ca.crt'))
            ctx.load_cert_chain(self._path('server.crt'), self._path('server.key'))
            return ctx
