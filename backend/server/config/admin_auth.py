"""Server administrator credentials stored beside the runtime database."""

import json
import os
import re
import secrets
import stat
import tempfile

from werkzeug.security import generate_password_hash


_PASSWORD_METHOD = 'scrypt:32768:8:1'
_PASSWORD_HASH_RE = re.compile(r'scrypt:32768:8:1\$[A-Za-z0-9_-]+\$[0-9a-f]{128}\Z')


def _write_auth_file(path, credentials, *, create_only=False):
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix='.auth-', dir=directory)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(credentials, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if create_only:
            # Publish a fully written file without overwriting a concurrent startup.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_auth_file(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Auth configuration is not a regular file: {path}')
    os.chmod(path, 0o600)
    with open(path, encoding='utf-8') as stream:
        credentials = json.load(stream)
    if not isinstance(credentials, dict) or set(credentials) != {
        'username', 'password', 'api_token', 'session_secret',
    }:
        raise ValueError(f'Invalid auth configuration fields: {path}')
    for name in ('username', 'password', 'api_token', 'session_secret'):
        if not isinstance(credentials[name], str) or not credentials[name].strip():
            raise ValueError(f'Invalid auth configuration {name}: {path}')
    if len(credentials['api_token']) < 32 or len(credentials['session_secret']) < 32:
        raise ValueError(f'Auth configuration contains a short token or session secret: {path}')

    password = credentials['password']
    if password.startswith('plain:'):
        plain_password = password[len('plain:'):]
        if not plain_password:
            raise ValueError(f'Empty plaintext administrator password: {path}')
        credentials['password'] = generate_password_hash(plain_password, method=_PASSWORD_METHOD)
        _write_auth_file(path, credentials)
    elif not _PASSWORD_HASH_RE.fullmatch(password):
        raise ValueError(f'Invalid administrator password hash in {path}; use plain:<password> to reset')
    return credentials


def load_admin_auth(path):
    """Create once if absent; on later starts accept only valid persisted credentials."""
    try:
        return _read_auth_file(path)
    except FileNotFoundError:
        pass

    password = secrets.token_urlsafe(24)
    credentials = {
        'username': 'admin',
        'password': generate_password_hash(password, method=_PASSWORD_METHOD),
        'api_token': secrets.token_urlsafe(32),
        'session_secret': secrets.token_urlsafe(48),
    }
    try:
        _write_auth_file(path, credentials, create_only=True)
    except FileExistsError:
        return _read_auth_file(path)
    print(f'[RCH] Initial administrator username: {credentials["username"]}', flush=True)
    print(f'[RCH] Initial administrator password: {password}', flush=True)
    return credentials
