"""Immutable, server-owned cleanup candidates and filesystem signatures."""
from dataclasses import dataclass
from pathlib import Path
import os
import stat
import uuid


@dataclass(frozen=True)
class PathEntry:
    path: str
    identity: tuple
    directory: bool
    size: int


def inspect_path(path):
    path = Path(path).absolute()
    # Refuse symlinked ancestors and special files. Runtime roots are private to
    # the Server; never follow a link into an unrelated directory.
    if path.resolve() != path:
        raise ValueError(f'Unsafe path: {path}')
    entries = []
    device = path.lstat().st_dev

    def visit(current):
        info = current.lstat()
        directory = stat.S_ISDIR(info.st_mode)
        if info.st_dev != device or (directory and os.path.ismount(current)):
            raise ValueError(f'Mounted path is protected: {current}')
        if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError(f'Unsupported file: {current}')
        entries.append(PathEntry(str(current), (info.st_dev, info.st_ino, info.st_mode,
                         info.st_size, info.st_mtime_ns, info.st_ctime_ns),
                         directory, 0 if directory else info.st_size))
        if directory:
            for child in sorted(current.iterdir()):
                visit(child)
    visit(path)
    return tuple(entries)


@dataclass(frozen=True)
class Candidate:
    category: str
    key: str
    name: str
    modified: float
    entries: tuple = ()
    record: bool = False
    # Record metadata may be needed for revalidation, never accepted from UI.
    signature: str = ''
    id: str = ''

    @classmethod
    def file(cls, category, key, path, name=None, record=False, signature=''):
        entries = inspect_path(path)
        return cls(category, str(key), name or Path(path).name,
                   max(entry.identity[4] for entry in entries) / 1e9, entries, record, signature, uuid.uuid4().hex)

    @property
    def size(self):
        return sum(entry.size for entry in self.entries)

    def as_dict(self):
        root = Path(self.entries[0].path) if self.entries else None
        return {'id': self.id, 'name': self.name, 'path': str(root) if root else '',
                'size': self.size, 'modified': self.modified, 'record': self.record,
                'files': sum(not e.directory for e in self.entries),
                'dirs': sum(e.directory for e in self.entries),
                'children': [{'path': str(Path(e.path).relative_to(root)), 'size': e.size,
                              'directory': e.directory} for e in self.entries[1:]]}

    def unchanged(self):
        if not self.entries:
            return True
        try:
            return self.entries == inspect_path(self.entries[0].path)
        except (OSError, ValueError):
            return False

    def remove_files(self, result):
        # Do not rmtree: files created after the approved scan must not be
        # deleted. Remove known leaves, then only empty known directories.
        if not self.unchanged():
            raise ValueError('Candidate changed; scan again')
        for entry in reversed(self.entries):
            path = Path(entry.path)
            if path.resolve() != path:
                raise ValueError('Candidate path changed')
            if entry.directory:
                current = path.lstat()
                if (current.st_dev, current.st_ino) != entry.identity[:2]:
                    raise ValueError('Candidate directory changed')
                path.rmdir()
                result['removed_dirs'] += 1
            else:
                if inspect_path(path) != (entry,):
                    raise ValueError('Candidate file changed')
                path.unlink()
                result['removed_files'] += 1
                result['bytes_freed'] += entry.size
            result['entries'].append({'kind': 'dir' if entry.directory else 'file',
                                      'path': entry.path, 'size': entry.size, 'detail': ''})
