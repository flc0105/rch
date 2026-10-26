import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PosixUserIdentity:
    uid: int
    gid: int
    username: str
    home: str

    def as_dict(self) -> dict:
        return {
            'uid': int(self.uid),
            'gid': int(self.gid),
            'username': str(self.username),
            'home': str(self.home),
        }


def _pwd_module():
    try:
        import pwd
        return pwd
    except ImportError as exc:
        raise RuntimeError('POSIX account lookup is unavailable on this platform') from exc


def _identity_from_record(record) -> PosixUserIdentity:
    return PosixUserIdentity(
        uid=int(record.pw_uid),
        gid=int(record.pw_gid),
        username=str(record.pw_name or '').strip(),
        home=str(record.pw_dir or '').strip(),
    )


def get_posix_user_identity(user=None) -> PosixUserIdentity:
    """Resolve a POSIX account by uid or username."""
    pwd = _pwd_module()
    if user is None or str(user).strip() == '':
        getter = getattr(os, 'geteuid', None)
        if getter is None:
            raise RuntimeError('Effective UID is unavailable on this platform')
        return _identity_from_record(pwd.getpwuid(int(getter())))

    text = str(user).strip()
    if text.isdigit():
        return _identity_from_record(pwd.getpwuid(int(text)))
    return _identity_from_record(pwd.getpwnam(text))


def get_macos_console_user_identity():
    """Return the active macOS console user, or None when no GUI user is logged in."""
    if os.name != 'posix':
        return None

    try:
        uid = int(os.stat('/dev/console').st_uid)
        if uid <= 0:
            return None
        identity = get_posix_user_identity(uid)
        if identity.username in {'root', 'loginwindow', '_mbsetupuser'}:
            return None
        return identity
    except Exception:
        return None


def resolve_macos_target_user_identity(target_user=None) -> PosixUserIdentity:
    """Resolve the user whose GUI launchd domain / home directory is being targeted."""
    if target_user is not None and str(target_user).strip():
        identity = get_posix_user_identity(target_user)
        if identity.uid <= 0:
            raise RuntimeError('LaunchAgent target user must be a non-root account')
        return identity

    getter = getattr(os, 'geteuid', None)
    if getter is None:
        raise RuntimeError('Effective UID is unavailable on this platform')

    effective_uid = int(getter())
    if effective_uid > 0:
        return get_posix_user_identity(effective_uid)

    sudo_uid = str(os.environ.get('SUDO_UID') or '').strip()
    if sudo_uid.isdigit() and int(sudo_uid) > 0:
        try:
            return get_posix_user_identity(int(sudo_uid))
        except Exception:
            pass

    sudo_user = str(os.environ.get('SUDO_USER') or '').strip()
    if sudo_user and sudo_user != 'root':
        try:
            identity = get_posix_user_identity(sudo_user)
            if identity.uid > 0:
                return identity
        except Exception:
            pass

    identity = get_macos_console_user_identity()
    if identity is not None:
        return identity

    raise RuntimeError(
        'No target GUI user could be resolved; provide target_user explicitly'
    )
