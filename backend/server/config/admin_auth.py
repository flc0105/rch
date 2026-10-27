"""Server administrator credentials stored beside the runtime database."""

import json
import os
import re
import secrets
import stat
import tempfile

from werkzeug.security import check_password_hash, generate_password_hash


_PASSWORD_METHOD = 'scrypt:32768:8:1'
_PASSWORD_HASH_RE = re.compile(r'scrypt:32768:8:1\$[A-Za-z0-9_-]+\$[0-9a-f]{128}\Z')
_ENGLISH_LETTER_RE = re.compile(r'[A-Za-z]')
_DIGIT_RE = re.compile(r'[0-9]')


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


def validate_admin_password(password):
    value = str(password or '')
    if len(value) < 8:
        raise ValueError('Password must be at least 8 characters')
    if not _ENGLISH_LETTER_RE.search(value):
        raise ValueError('Password must include at least one English letter')
    if not _DIGIT_RE.search(value):
        raise ValueError('Password must include at least one digit')
    return value


def change_admin_password(path, current_password, new_password):
    credentials = _read_auth_file(path)
    if not check_password_hash(credentials['password'], str(current_password or '')):
        raise PermissionError('Current password is incorrect')

    updated = dict(credentials)
    updated['password'] = generate_password_hash(
        validate_admin_password(new_password),
        method=_PASSWORD_METHOD,
    )
    _write_auth_file(path, updated)
    return updated


def reset_admin_api_token(path):
    """Rotate the administrator API token while preserving other credentials."""
    credentials = _read_auth_file(path)
    updated = dict(credentials)
    updated['api_token'] = secrets.token_urlsafe(32)
    _write_auth_file(path, updated)
    return updated


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
