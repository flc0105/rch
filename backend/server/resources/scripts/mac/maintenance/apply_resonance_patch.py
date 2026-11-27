SCRIPT_METADATA = {
    'name': 'mac/maintenance/apply_resonance_patch',
    'display_name': 'Apply RESONANCE Patch',
    'description': 'Preview and approve the latest RESONANCE ZIP patch from a dedicated download directory.',
    'platforms': ['mac'],
    'category': 'Maintenance',
    'params': [
        {'name': 'project_dir', 'label': 'RESONANCE project directory', 'type': 'string',
         'default': '/Users/flc/PycharmProjects/resonance'},
        {'name': 'patch_dir', 'label': 'Patch download directory', 'type': 'string',
         'default': '~/Downloads/RCH-Patches'},
    ],
}

import hashlib
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from client.runtime.sdk import context


# ZIP entries are relative to the project root, without a resonance/ wrapper.
# A full project snapshot (resonance_project_*.zip) is never selected here.
PATCH_PATTERN = re.compile(r'resonance_v\d+\.\d+\.\d+(?:[-.][A-Za-z0-9][A-Za-z0-9.-]*)?_patch(?: \(\d+\))?\.zip\Z')
ALLOWED_ROOTS = frozenset({'backend', 'frontend', 'tests', 'tools'})
ALLOWED_ROOT_FILES = frozenset({
    'README.md', 'README-MAC.md', 'TEST-REPORT.md', 'CHANGELOG.md',
    'requirements.txt', 'config.example.json', '.gitignore', '.env.example',
    '.env.sample', '.env.template', 'setup.sh', 'setup-mac.sh', 'start.sh',
    'dev.py', 'zip_project.py',
})
IGNORE_DIR_NAMES = frozenset({
    '__pycache__', 'pycache', '.venv', 'venv', 'node_modules', '.git',
    '.idea', '.vscode', '.vite', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    '.tox', '.nox', '.cache', '__macosx', 'backups',
})
IGNORE_FILE_NAMES = frozenset({'.ds_store', 'thumbs.db', 'desktop.ini', 'nohup.out', '.silverbullet.auth.json'})
IGNORE_SUFFIXES = frozenset({'.pyc', '.pyo', '.bak', '.swp', '.swo', '.db', '.sqlite', '.sqlite3', '.pem', '.key', '.p12', '.pfx'})
ENV_EXAMPLES = frozenset({'.env.example', '.env.sample', '.env.template'})
ARCHIVE_SUFFIXES = ('.zip', '.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz', '.7z', '.rar')
LOG_PATTERN = re.compile(r'\.log(?:\.\d+)?(?:\.gz)?$', re.IGNORECASE)
IGNORE_PATHS = {PurePosixPath(p) for p in (
    'data', 'frontend/dist', 'frontend/coverage', 'backend/data', 'backend/runtime',
    'backend/config.json', 'backend/cache', 'backend/artwork', 'backend/logs',
)}
ARCHIVE_INPUT_ROOTS = {PurePosixPath(p) for p in ('tests', 'backend/tests', 'frontend/tests')}
MAX_ENTRIES = 3000
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


def canonical(value):
    return unicodedata.normalize('NFC', str(value)).casefold()


def is_within(relative, roots):
    return any(relative == root or root in relative.parents for root in roots)


def protected(relative, is_dir=False):
    rel = PurePosixPath(canonical(relative.as_posix()))
    if is_within(rel, IGNORE_PATHS):
        return True
    if any(part in IGNORE_DIR_NAMES for part in rel.parts):
        return True
    if is_dir:
        return False
    name = rel.name
    return (name in IGNORE_FILE_NAMES or rel.suffix in IGNORE_SUFFIXES
            or name.endswith(('~', '-wal', '-shm', '-journal')) or bool(LOG_PATTERN.search(name))
            or ((name == '.env' or name.startswith('.env.')) and name not in ENV_EXAMPLES)
            or (name.endswith(ARCHIVE_SUFFIXES) and not is_within(rel, ARCHIVE_INPUT_ROOTS)))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def latest_patch(directory):
    directory.mkdir(parents=True, exist_ok=True)
    options = [p for p in directory.glob('resonance_v*_patch*.zip')
               if PATCH_PATTERN.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    if not options:
        raise FileNotFoundError(f'No resonance_v<version>_patch.zip patch found in {directory}')
    return max(options, key=lambda p: (p.stat().st_mtime_ns, p.name))


def verify_target(project, relative, is_dir=False):
    target = project.joinpath(*relative.parts)
    current = project
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise ValueError(f'Unsafe directory in patch target: {current}')
    if target.is_symlink() or (target.exists() and not (target.is_dir() if is_dir else target.is_file())):
        raise ValueError(f'Unsafe patch target: {target}')
    return target


def identity_of(target):
    if not target.exists():
        return None
    info = target.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode, file_sha256(target))


def inspect_patch(project, zip_path):
    entries = []
    seen = {}
    explicit = set()
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError('ZIP contains too many entries')
        for info in infos:
            name = info.filename
            original_name = info.orig_filename
            parts = name.rstrip('/').split('/')
            is_dir = info.is_dir()
            if (not name or name.startswith('/') or '\\' in original_name or '\x00' in original_name
                    or name != original_name or any(part in ('', '.', '..') for part in parts)
                    or not ((len(parts) == 1 and parts[0] in ALLOWED_ROOT_FILES and not is_dir)
                            or (parts[0] in ALLOWED_ROOTS and (len(parts) >= 2 or is_dir)))):
                raise ValueError(f'Unsafe ZIP entry: {original_name!r}')
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1
                    or (is_dir and mode == stat.S_IFREG) or (not is_dir and mode == stat.S_IFDIR)):
                raise ValueError(f'Unsupported or encrypted ZIP entry: {name}')
            relative = PurePosixPath(*parts)
            if protected(relative, is_dir):
                raise ValueError(f'Protected project path: {relative}')
            # Reject path aliases, duplicate entries and directory/file collisions,
            # including case and Unicode aliases on default macOS filesystems.
            for i in range(1, len(parts)+1):
                prefix = '/'.join(parts[:i])
                key = canonical(prefix)
                kind = 'dir' if i < len(parts) or is_dir else 'file'
                if key in seen and seen[key] != (prefix, kind):
                    raise ValueError(f'Conflicting ZIP path: {name}')
                seen[key] = (prefix, kind)
            key = canonical(relative.as_posix())
            if key in explicit:
                raise ValueError(f'Duplicate ZIP path: {name}')
            explicit.add(key)
            target = verify_target(project, relative, is_dir)
            if is_dir:
                if info.file_size:
                    raise ValueError(f'Invalid directory entry: {name}')
                continue
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError('Patch is too large')
            entries.append((name, relative, identity_of(target)))
        # Check the expansion limits before reading/decompressing the archive.
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC check failed')
    if not entries:
        raise ValueError('Patch contains no files')
    return entries


def atomic_copy(source, target, mode):
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.resonance-patch-', delete=False) as temp:
        pending = Path(temp.name)
        try:
            shutil.copyfileobj(source, temp)
            temp.flush()
            os.fsync(temp.fileno())
        except BaseException:
            pending.unlink(missing_ok=True)
            raise
    try:
        os.chmod(pending, mode)
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)


def apply_patch(project, archive_path, entries, backup_root):
    # Backup all originals before replacing any file; rollback on write errors.
    for _, relative, identity in entries:
        target = verify_target(project, relative)
        if identity_of(target) != identity:
            raise RuntimeError(f'Target changed after preview: {relative}')
        if identity is not None:
            destination = backup_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
            if file_sha256(destination) != identity[-1]:
                raise RuntimeError(f'Target changed while backing up: {relative}')

    touched = []
    created_dirs = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for name, relative, identity in entries:
                target = verify_target(project, relative)
                if identity_of(target) != identity:
                    raise RuntimeError(f'Target changed before replacement: {relative}')
                current = project
                for part in relative.parts[:-1]:
                    current = current / part
                    if not current.exists():
                        current.mkdir()
                        created_dirs.append(current)
                mode = (identity[4] & 0o777) if identity else (0o755 if target.suffix == '.sh' else 0o644)
                with archive.open(name) as source:
                    atomic_copy(source, target, mode)
                touched.append((target, relative, identity))
    except BaseException:
        failures = []
        for target, relative, identity in reversed(touched):
            try:
                if identity is None:
                    target.unlink(missing_ok=True)
                else:
                    original = backup_root.joinpath(*relative.parts)
                    with original.open('rb') as source:
                        atomic_copy(source, target, identity[4] & 0o777)
                    shutil.copystat(original, target)
            except Exception as exc:
                failures.append(f'{relative}: {exc}')
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        if failures:
            raise RuntimeError(f'Rollback incomplete; recover from {backup_root}: {failures}')
        raise


def main(params):
    project = Path(str(params.get('project_dir') or SCRIPT_METADATA['params'][0]['default'])).expanduser().resolve()
    patch_dir = Path(str(params.get('patch_dir') or SCRIPT_METADATA['params'][1]['default'])).expanduser().resolve()
    if not ((project / 'backend/app.py').is_file() and (project / 'frontend/src/App.vue').is_file()
            and (project / 'frontend/package.json').is_file()):
        raise ValueError(f'Not a RESONANCE project root: {project}')
    if patch_dir == project or project in patch_dir.parents:
        raise ValueError('Patch download and backup directory must be outside the project')
    archive = latest_patch(patch_dir)
    checksum = file_sha256(archive)
    entries = inspect_patch(project, archive)
    if file_sha256(archive) != checksum:
        raise RuntimeError('Patch ZIP changed during preview preparation')
    replacements = sum(identity is not None for _, _, identity in entries)
    additions = len(entries) - replacements
    preview = {
        'summary': [
            {'label': 'Patch', 'value': archive.name},
            {'label': 'Project', 'value': str(project)},
            {'label': 'Replace existing', 'value': str(replacements)},
            {'label': 'Add new', 'value': str(additions)},
            {'label': 'SHA-256', 'value': checksum[:16]},
        ],
        'columns': [{'key': 'action', 'label': 'Action'}, {'key': 'file', 'label': 'Project file'}],
        'rows': [{'action': 'Replace' if identity else 'Add', 'file': str(relative)}
                 for _, relative, identity in entries[:30]],
        'notice': ('Overwrite source files only after approval. Existing files are backed up; '
                   'no file deletions, no dependency installs or restarts. Stop running development servers '
                   'before approval. Only apply trusted patches. '
                   + (f'Showing first 30 of {len(entries)} files. ' if len(entries) > 30 else '')
                   + 'Local music, data/, .env and caches are not patch targets.'),
    }
    if not context.approve_preview('Apply the selected RESONANCE patch?', preview,
                                   title='Apply RESONANCE Patch', timeout=180):
        print('Patch cancelled; no project files changed.')
        return
    if file_sha256(archive) != checksum:
        raise RuntimeError('Patch ZIP changed after preview')
    # Work from a private copy so a download changing mid-apply cannot alter the patch.
    with tempfile.TemporaryDirectory(prefix='resonance-patch-') as temp:
        snapshot = Path(temp) / archive.name
        shutil.copyfile(archive, snapshot)
        if file_sha256(snapshot) != checksum or inspect_patch(project, snapshot) != entries:
            raise RuntimeError('Patch contents or target files changed after preview')
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup = patch_dir / 'backups' / f'{archive.stem}_{stamp}'
        backup.mkdir(parents=True, exist_ok=False)
        apply_patch(project, snapshot, entries, backup)
    print(f'Applied: {archive.name} ({replacements} replaced, {additions} added)')
    print(f'Backup: {backup}')
    if any(str(relative) == 'requirements.txt' for _, relative, _ in entries):
        print('Python dependencies changed: .venv/bin/python -m pip install -r requirements.txt')
    if any(str(relative) in {'frontend/package.json', 'frontend/package-lock.json'} for _, relative, _ in entries):
        print('Frontend dependencies changed: cd frontend && npm install (or npm ci if lockfile is current)')
    print('Restart backend: source .venv/bin/activate && python3 dev.py')
    print('Restart frontend: nvm use 20 && cd frontend && npm run dev')


if __name__ == '__main__':
    main(kwargs)
