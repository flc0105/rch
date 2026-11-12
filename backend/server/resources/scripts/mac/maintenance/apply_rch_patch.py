SCRIPT_METADATA = {
    'name': 'mac/maintenance/apply_rch_patch',
    'display_name': 'Apply RCH Patch',
    'description': 'Preview and approve the latest RCH ZIP patch from a dedicated download directory.',
    'platforms': ['mac'],
    'category': 'Maintenance',
    'params': [
        {'name': 'project_dir', 'label': 'RCH project directory', 'type': 'string',
         'default': '/Users/flc/PycharmProjects/rch'},
        {'name': 'patch_dir', 'label': 'Patch download directory', 'type': 'string',
         'default': '~/Downloads/RCH-Patches'},
    ],
}

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from client.runtime.sdk import context


ALLOWED_ROOTS = frozenset({'backend', 'frontend', 'tools', 'desktop_notifier'})
MAX_ENTRIES = 3000
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def latest_patch(directory):
    directory.mkdir(parents=True, exist_ok=True)
    options = [p for p in directory.glob('rch_v*.zip') if p.is_file() and not p.is_symlink()]
    if not options:
        raise FileNotFoundError(f'No rch_v*.zip patch found in {directory}')
    return max(options, key=lambda p: (p.stat().st_mtime_ns, p.name))


def verify_target(project, relative):
    target = project.joinpath(*relative.parts)
    current = project
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise ValueError(f'Unsafe directory in patch target: {current}')
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(f'Unsafe patch target: {target}')
    return target


def inspect_patch(project, zip_path):
    entries = []
    seen = set()
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC check failed')
        if len(archive.infolist()) > MAX_ENTRIES:
            raise ValueError('ZIP contains too many entries')
        for info in archive.infolist():
            name = info.filename
            parts = name.rstrip('/').split('/')
            if (not name or name.startswith('/') or '\\' in name or '\x00' in name
                    or any(part in ('', '.', '..') for part in parts)
                    or parts[0] not in ALLOWED_ROOTS or len(parts) < 2):
                raise ValueError(f'Unsafe ZIP entry: {name!r}')
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f'Unsupported ZIP entry type: {name}')
            if info.is_dir():
                continue
            if mode == stat.S_IFDIR or info.flag_bits & 1:
                raise ValueError(f'Invalid or encrypted ZIP entry: {name}')
            relative = PurePosixPath(*parts)
            canonical = relative.as_posix().casefold()
            if canonical in seen:
                raise ValueError(f'Duplicate ZIP path: {name}')
            seen.add(canonical)
            target = verify_target(project, relative)
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError('Patch is too large')
            original = target.stat() if target.exists() else None
            identity = ((original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns)
                        if original else None)
            entries.append((info.filename, relative, identity))
    if not entries:
        raise ValueError('Patch contains no files')
    return entries


def apply_patch(project, archive_path, entries, backup_root):
    # Backup all originals before the first replacement; rollback on write errors.
    for _, relative, identity in entries:
        target = verify_target(project, relative)
        info = target.stat() if target.exists() else None
        current = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) if info else None
        if current != identity:
            raise RuntimeError(f'Target changed after preview: {relative}')
    for _, relative, identity in entries:
        if identity is not None:
            destination = backup_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project.joinpath(*relative.parts), destination)

    touched = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for name, relative, identity in entries:
                target = verify_target(project, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.rch-patch-', delete=False) as temp:
                    pending = Path(temp.name)
                    try:
                        with archive.open(name) as source:
                            shutil.copyfileobj(source, temp)
                        temp.flush()
                        os.fsync(temp.fileno())
                    except BaseException:
                        pending.unlink(missing_ok=True)
                        raise
                try:
                    if identity is not None:
                        os.chmod(pending, target.stat().st_mode & 0o777)
                    os.replace(pending, target)
                finally:
                    pending.unlink(missing_ok=True)
                touched.append((target, relative, identity))
    except BaseException:
        for target, relative, identity in reversed(touched):
            if identity is None:
                target.unlink(missing_ok=True)
            else:
                shutil.copy2(backup_root.joinpath(*relative.parts), target)
        raise


def main(params):
    project = Path(str(params.get('project_dir') or SCRIPT_METADATA['params'][0]['default'])).expanduser().resolve()
    patch_dir = Path(str(params.get('patch_dir') or SCRIPT_METADATA['params'][1]['default'])).expanduser().resolve()
    if not ((project / 'backend/run_web.py').is_file() and (project / 'frontend/src/App.vue').is_file()):
        raise ValueError(f'Not an RCH project root: {project}')
    archive = latest_patch(patch_dir)
    entries = inspect_patch(project, archive)
    checksum = file_sha256(archive)
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
        'notice': 'Overwrite project files only after approval. Existing files are backed up. '
                  'Start the updated Server and Client after applying the patch.',
    }
    if not context.approve_preview('Apply the selected RCH patch?', preview,
                                   title='Apply RCH Patch', timeout=180):
        print('Patch cancelled; no files changed.')
        return
    if file_sha256(archive) != checksum:
        raise RuntimeError('Patch ZIP changed after preview')
    if inspect_patch(project, archive) != entries:
        raise RuntimeError('Patch contents or target files changed after preview')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = patch_dir / 'backups' / f'{archive.stem}_{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    apply_patch(project, archive, entries, backup)
    print(f'Applied: {archive.name} ({replacements} replaced, {additions} added)')
    print(f'Backup: {backup}')
    print('Restart RCH Server; update/restart Clients if Client files changed.')


if __name__ == '__main__':
    main(kwargs)
