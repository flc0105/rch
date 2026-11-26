"""Browser upload selection: relative paths, directory ancestors and stable order."""
from dataclasses import dataclass

from server.config.transfer_limits import WEB_HTTP_UPLOAD_MAX_BYTES


def validate_upload_size(size):
    if type(size) is not int or not 0 <= size <= WEB_HTTP_UPLOAD_MAX_BYTES:
        raise ValueError('Invalid upload byte count or HTTP size limit exceeded')


def upload_path_parts(path):
    if not isinstance(path, str) or not path:
        raise ValueError('Invalid upload path')
    parts = path.split('/')
    if any(not part or part in ('.', '..') or '\\' in part or any(ord(ch) < 32 for ch in part) for part in parts):
        raise ValueError('Invalid upload path')
    return parts


@dataclass(frozen=True)
class UploadPlan:
    files: tuple[str, ...]
    directories: tuple[str, ...]

    @classmethod
    def build(cls, paths, directories, *, max_folders=10000):
        if not isinstance(paths, (list, tuple)) or not isinstance(directories, (list, tuple)):
            raise ValueError('Invalid upload plan')
        if len(paths) > 1000 or len(directories) > max_folders or not (paths or directories):
            raise ValueError('Invalid upload plan size')
        folders = set()
        files = []
        for path in directories:
            parts = upload_path_parts(path)
            folders.update('/'.join(parts[:i]) for i in range(1, len(parts) + 1))
        for path in paths:
            parts = upload_path_parts(path)
            files.append(path)
            folders.update('/'.join(parts[:i]) for i in range(1, len(parts)))
        if len(folders) > max_folders or len(files) != len(set(files)) or folders.intersection(files):
            raise ValueError('Invalid or duplicate upload path')
        return cls(tuple(files), tuple(sorted(folders, key=lambda value: (value.count('/'), value))))


@dataclass(frozen=True)
class RemoteUploadMember:
    relative_path: str
    destination_path: str
    filename: str
    size: int
    conflict_policy: str


def remote_upload_members(root, files, directories):
    """Bind wire members to the selected root without using the Server OS path rules."""
    if not isinstance(root, str) or not root or root != root.strip():
        raise ValueError('Invalid upload destination')
    if not isinstance(files, list) or any(not isinstance(item, dict) for item in files):
        raise ValueError('Invalid upload members')
    plan = UploadPlan.build([item.get('relative_path') for item in files], directories)
    separator = '\\' if not root.startswith('/') and ('\\' in root or (len(root) >= 2 and root[1] == ':')) else '/'
    members = []
    for path in (*plan.files, *plan.directories):
        # Current Client path resolvers trim whitespace; reject ambiguous names up front.
        if any(part != part.strip() for part in path.split('/')):
            raise ValueError(f'Invalid upload path: {path}')
    for path, item in zip(plan.files, files):
        size = item.get('size')
        policy = item.get('conflict_policy')
        validate_upload_size(size)
        if policy not in ('stop', 'replace', 'keep_both'):
            raise ValueError('Invalid upload member size or policy')
        parent, _, name = path.rpartition('/')
        destination = root.rstrip('/\\' if separator == '\\' else '/') + separator + parent.replace('/', separator) if parent else root
        members.append(RemoteUploadMember(path, destination, name, size, policy))
    return plan, tuple(members)
