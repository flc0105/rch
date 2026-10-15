"""Read-only expansion of a single directory-level * in a path under user home."""
import os
import stat
from pathlib import Path

_OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def expand_directory_pattern(pattern: str) -> list[Path]:
    """Expand ``.../*/msg/file`` to existing directories, without following links.

    No files are deleted. Callers must separately snapshot and approve any changes.
    """
    if not isinstance(pattern, str) or not pattern.strip() or '\x00' in pattern:
        raise ValueError('Directory pattern must be a nonempty path')
    raw = (Path.home() / pattern.strip()[2:] if pattern.strip().startswith('~/')
           else Path(os.path.expanduser(pattern.strip())))
    if not raw.is_absolute() or '..' in raw.parts:
        raise ValueError('Directory pattern must be absolute without parent traversal')
    home = Path.home().absolute()
    if home not in raw.parents:
        raise ValueError('Directory pattern must be inside user home')
    relative = raw.relative_to(home).parts
    if sum(part == '*' for part in relative) != 1 or relative[-1] == '*':
        raise ValueError('Exactly one intermediate * directory is required')
    if any(any(char in part for char in '*?[]') for part in relative if part != '*'):
        raise ValueError('Only one complete * directory segment is supported')
    position = relative.index('*')
    base = home.joinpath(*relative[:position])
    suffix = relative[position + 1:]
    fd = os.open('/', _OPEN_DIR)
    try:
        for part in base.parts[1:]:
            next_fd = os.open(part, _OPEN_DIR, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        with os.scandir(fd) as listing:
            names = sorted(entry.name for entry in listing if entry.is_dir(follow_symlinks=False))
        matches = []
        for name in names:
            child_fd = None
            try:
                child_fd = os.open(name, _OPEN_DIR, dir_fd=fd)
                for part in suffix:
                    next_fd = os.open(part, _OPEN_DIR, dir_fd=child_fd)
                    os.close(child_fd)
                    child_fd = next_fd
                if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
                    continue
                matches.append(base / name / Path(*suffix))
                if len(matches) > 100:
                    raise ValueError('Directory pattern matches more than 100 targets')
            except OSError:
                continue
            finally:
                if child_fd is not None:
                    os.close(child_fd)
        return matches
    finally:
        os.close(fd)
