SCRIPT_METADATA = {
    "name": "mac/maintenance/personal_cleanup",
    "display_name": "Personal Cleanup",
    "description": "Preview and approve cleanup.",
    "platforms": ["mac"],
    "category": "Maintenance",
    "api_grants": ["interactions:request"],
    "params": [
        {"name": "cleanup_paths", "label": "Cleanup paths",
         "type": "path_list", "required": False,
         "description": "Choose what to clean. Deletion is permanent after approval.",
         "default": [
             {"path": "/Users/flc/Work/Home/seeyona9/ApacheJetspeed/logs_sy", "enabled": True},
             {"path": "~/SeeyonLogs", "enabled": True},
             {"path": "~/NCCACHE", "enabled": True},
             {"path": "~/upload/files", "enabled": True},
             {"path": "~/Library/ScreenRecordings", "enabled": True},
             {"path": "~/Library/Caches/Google/Chrome/Default", "enabled": True},
             {"path": "~/Library/Application Support/Google/Chrome/Default/Service Worker/CacheStorage", "enabled": False},
             {"path": "~/Library/Containers/com.apple.Safari/Data/Library/Caches/com.apple.Safari", "enabled": True},
             {"path": "~/Library/Developer/Xcode/DerivedData", "enabled": True},
             {"path": "~/Library/Logs/Adobe", "enabled": True},
             {"path": "~/Library/Caches/Adobe Camera Raw 2", "enabled": True},
             {"path": "~/Library/Caches/Adobe/CCX Welcome", "enabled": True},
             {"path": "~/Library/Caches/Homebrew", "enabled": True},
             {"path": "~/Library/Caches/pip", "enabled": True},
             {"path": "~/Library/Logs/JetBrains/", "enabled": True},
             {"path": "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/*/msg/file", "enabled": False},
             
             {"path": "~/*.hprof", "enabled": True},
             {"path": "~/.Trash", "enabled": False},
         ]},
    ],
}

# Deletion policy: NEVER remove a selected root, enter symlinked directories,
# traverse another filesystem, or delete an item that changed after scanning.
# Editable paths must stay under home or an actual /Volumes/<name>/... mount.
# Finder Trash is a separate approved action; ~/*.hprof matches only home-level regular files.

import os
import stat
import subprocess
from pathlib import Path

from client.runtime.sdk import context
from client.runtime.sdk.interactions import ScriptSdkInteractionError
from client.runtime.sdk.path_patterns import expand_directory_pattern


OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def readable_size(count):
    count = float(count)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if count < 1024 or unit == 'TiB':
            return f'{count:.0f} {unit}' if unit == 'B' else f'{count:.2f} {unit}'
        count /= 1024


def emit(message, *, warning=False):
    context.progress(('[WARNING] ' if warning else '[CLEANUP] ') + message,
                     status=0 if warning else 1)


def identity(info, *, directory=False):
    # mtime/size for files and links, only dev/inode/type for directories:
    # directory mtimes change naturally as their children are removed.
    base = (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
    return base if directory else base + (info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _safe_root(text):
    if not isinstance(text, str) or not text.strip() or '\x00' in text:
        raise ValueError('Cleanup path must be a nonempty directory path')
    candidate = Path(os.path.abspath(os.path.expanduser(text.strip())))
    if not candidate.is_absolute():
        raise ValueError('Cleanup path must resolve to absolute')
    home = Path.home().absolute()
    if any('*' in part for part in candidate.parts) and candidate != home / '*.hprof':
        # Only a complete, non-terminal * directory level is allowed.
        if (candidate.parts.count('*') != 1 or candidate.parts[-1] == '*' or
                home not in candidate.parents or '..' in Path(text.strip()).parts or
                any('*' in part and part != '*' for part in candidate.parts)):
            raise ValueError('Only one intermediate * directory or ~/*.hprof is supported')
    # Prevent deleting broad system/user roots, while permitting editable paths.
    in_home = candidate != home and home in candidate.parents
    parts = candidate.parts
    on_volume = (len(parts) >= 5 and parts[1] == 'Volumes' and
                 Path('/', 'Volumes', parts[2]).is_mount())
    if not (in_home or on_volume):
        raise ValueError(f'Unsafe cleanup target outside home/volume: {candidate}')
    if candidate in (home / 'Library', home / 'Documents', home / 'Downloads',
                     home / 'Desktop', home / '.npm', home / '.nvm'):
        raise ValueError(f'Unsafe broad cleanup target: {candidate}')
    return candidate


def _open_path_no_symlinks(directory):
    """Open each component with O_NOFOLLOW (not just the final directory)."""
    fd = os.open('/', OPEN_DIRECTORY)
    try:
        for part in directory.parts[1:]:
            next_fd = os.open(part, OPEN_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def selected_directories(params):
    spec = next(p for p in SCRIPT_METADATA['params'] if p['name'] == 'cleanup_paths')
    entries = params.get('cleanup_paths', spec['default'])
    if not isinstance(entries, list):
        raise ValueError('cleanup_paths must be a path_list')
    chosen = []
    for row in entries:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str):
            raise ValueError('Each path_list row must contain a string path')
        if type(row.get('enabled', True)) is not bool:
            raise ValueError('path_list enabled must be boolean')
        if not row.get('enabled', True):
            continue
        root = _safe_root(row['path'])
        if '*' in root.parts:
            try:
                targets = expand_directory_pattern(str(root))
            except OSError as exc:
                emit(f'Skipping {root}: {exc}', warning=True)
                continue
        else:
            targets = [root]
        for target in targets:
            target = _safe_root(str(target))
            if any(target == previous or target in previous.parents or previous in target.parents
                   for previous in chosen):
                raise ValueError(f'Duplicate/overlapping cleanup target: {target}')
            chosen.append(target)
            if len(chosen) > 100:
                raise ValueError('Too many cleanup targets for a single Preview (maximum 100)')
    return chosen


def _scan_directory(root):
    """Snapshot direct file identities and directory identities; never follow links."""
    root_fd = _open_path_no_symlinks(root)
    try:
        root_info = os.fstat(root_fd)
        root_key = identity(root_info, directory=True)
        files, directories, skipped = [], {}, []
        file_size = 0

        def visit(fd, names):
            nonlocal file_size
            with os.scandir(fd) as listing:
                children = sorted(list(listing), key=lambda item: item.name)
            for child in children:
                path_parts = names + (child.name,)
                try:
                    info = os.stat(child.name, dir_fd=fd, follow_symlinks=False)
                    if info.st_dev != root_info.st_dev:
                        skipped.append(f'Cross-volume entry skipped: {"/".join(path_parts)}')
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        child_fd = os.open(child.name, OPEN_DIRECTORY, dir_fd=fd)
                        try:
                            if identity(os.fstat(child_fd), directory=True) != identity(info, directory=True):
                                raise OSError('directory changed during scan')
                            directories[path_parts] = identity(info, directory=True)
                            visit(child_fd, path_parts)
                        finally:
                            os.close(child_fd)
                    elif stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                        # Symlinks themselves are unlinked, but never traversed.
                        kind = 'link' if stat.S_ISLNK(info.st_mode) else 'file'
                        files.append((path_parts, identity(info), kind))
                        if kind == 'file':
                            file_size += info.st_size
                    else:
                        skipped.append(f'Special file skipped: {"/".join(path_parts)}')
                except OSError as exc:
                    skipped.append(f'Cannot scan {"/".join(path_parts)}: {exc}')
        visit(root_fd, ())
        # Refuse to delete anything in a root replaced during traversal.
        if identity(os.fstat(root_fd), directory=True) != root_key:
            raise OSError('Target directory changed during scan')
        return {'path': root, 'root_identity': root_key, 'files': files,
                'directories': directories, 'bytes': file_size, 'skipped': skipped}
    finally:
        os.close(root_fd)


def _scan_home_hprof(pattern):
    """Freeze only top-level home .hprof files; never scan home recursively."""
    root = pattern.parent
    fd = _open_path_no_symlinks(root)
    try:
        root_info = os.fstat(fd)
        root_key = identity(root_info, directory=True)
        files, skipped, total = [], [], 0
        with os.scandir(fd) as listing:
            names = sorted(entry.name for entry in listing
                           if entry.name.endswith('.hprof') and not entry.name.startswith('.'))
        for name in names:
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if info.st_dev != root_info.st_dev or not stat.S_ISREG(info.st_mode):
                    skipped.append(f'Not a regular file: {name}')
                    continue
                files.append(((name,), identity(info), 'file'))
                total += info.st_size
            except OSError as exc:
                skipped.append(f'Cannot scan {name}: {exc}')
        if identity(os.fstat(fd), directory=True) != root_key:
            raise OSError('Home directory changed during scan')
        return {'path': root, 'display_path': pattern, 'root_identity': root_key,
                'files': files, 'directories': {}, 'bytes': total, 'skipped': skipped}
    finally:
        os.close(fd)


def _finder_trash_count():
    """Read-only Finder preview probe; counts top-level items across Finder Trash."""
    try:
        process = subprocess.run(
            ['/usr/bin/osascript', '-e', 'tell application "Finder" to count items of trash'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OSError(f'Finder Trash query unavailable: {exc}') from exc
    if process.returncode:
        raise OSError(f'Finder Trash query failed: {(process.stderr or process.stdout).strip()[:300]}')
    try:
        count = int(process.stdout.strip())
    except ValueError as exc:
        raise OSError(f'Invalid Finder Trash item count: {process.stdout.strip()[:100]}') from exc
    if count < 0:
        raise OSError('Invalid negative Finder Trash item count')
    return count


def _empty_finder_trash(expected_count):
    """Finder owns Trash permissions; this action cannot freeze individual files."""
    try:
        current = _finder_trash_count()
        if current != expected_count:
            raise OSError(f'Finder Trash changed after Preview ({expected_count} to {current} items); not emptied')
        process = subprocess.run(
            ['/usr/bin/osascript', '-e', 'tell application "Finder" to empty trash'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600,
            check=False,
        )
        if process.returncode:
            raise OSError(f'Finder Empty Trash failed: {(process.stderr or process.stdout).strip()[:300]}')
        emit('Trash emptied.')
        return None
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)


def scan_plan(paths):
    scanned, warnings = [], []
    for index, root in enumerate(paths, 1):
        emit(f'[SCAN {index}/{len(paths)}] {root}')
        try:
            if root == Path.home().absolute() / '.Trash':
                count = _finder_trash_count()
                if not count:
                    emit('Trash is empty.')
                    continue
                data = {'path': root, 'finder_trash': True, 'trash_count': count,
                        'files': [], 'directories': {}, 'bytes': 0, 'skipped': []}
            else:
                data = (_scan_home_hprof(root) if root == Path.home().absolute() / '*.hprof'
                        else _scan_directory(root))
            scanned.append(data)
            if data.get('finder_trash'):
                emit(f'  Trash: {data["trash_count"]} items')
            else:
                emit(f'  {len(data["files"])} files/links, {len(data["directories"])} folders, '
                     f'{readable_size(data["bytes"])}')
            for message in data['skipped'][:15]:
                emit(f'{root}: {message}', warning=True)
            warnings.extend(f'{root}: {message}' for message in data['skipped'])
        except (OSError, ValueError) as exc:
            message = f'Skipping {root}: {exc}'
            warnings.append(message)
            emit(message, warning=True)
    return scanned, warnings


def _preview_label(item):
    target = item.get('display_path', item['path'])
    home = Path.home().absolute()
    labels = {
        home / 'Work/Home/seeyona9/ApacheJetspeed/logs_sy': 'Jetspeed Logs',
        home / 'SeeyonLogs': 'Seeyon Logs',
        home / 'NCCACHE': 'NC Cache',
        home / 'upload/files': 'Uploaded Files',
        home / 'Library/ScreenRecordings': 'Screen Recordings',
        home / 'Library/Caches/Google/Chrome/Default': 'Chrome Cache',
        home / 'Library/Application Support/Google/Chrome/Default/Service Worker/CacheStorage': 'Chrome Site Cache',
        home / 'Library/Containers/com.apple.Safari/Data/Library/Caches/com.apple.Safari': 'Safari Cache',
        home / 'Library/Developer/Xcode/DerivedData': 'Xcode DerivedData',
        home / 'Library/Logs/Adobe': 'Adobe Logs',
        home / 'Library/Caches/Adobe Camera Raw 2': 'Camera Raw Cache',
        home / 'Library/Caches/Adobe/CCX Welcome': 'Creative Cloud Cache',
        home / 'Library/Caches/Homebrew': 'Homebrew Cache',
        home / 'Library/Caches/pip': 'pip Cache',
        home / 'Library/Logs/JetBrains': 'JetBrains Logs',
        home / '*.hprof': 'Java Heap Dumps',
        home / '.Trash': 'Trash',
    }
    wechat_root = home / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
    if (target.name == 'file' and target.parent.name == 'msg' and
            target.parent.parent.parent == wechat_root):
        return 'WeChat Files'
    return labels.get(target, target.name)


def make_preview(scanned, warnings):
    count_files = sum(len(item['files']) for item in scanned)
    count_bytes = sum(item['bytes'] for item in scanned)
    rows = [{'label': _preview_label(item),
             'item': 'Trash (all disks)' if item.get('finder_trash')
             else str(item.get('display_path', item['path'])),
             'files': str(item["trash_count"]) if item.get('finder_trash')
             else str(len(item['files'])),
             'folders': '—' if item.get('finder_trash') else str(len(item['directories'])),
             'size': 'Unknown' if item.get('finder_trash')
             else readable_size(item['bytes'])} for item in scanned]
    row_details = []
    for index, item in enumerate(scanned, 1):
        if item.get('finder_trash'):
            continue
        names = ['/'.join(row[0]) for row in item['files'][:30]]
        if len(item['files']) > 30:
            names.append(f'... and {len(item["files"])-30} additional files/links')
        row_details.append({'row_id': str(index),
                            'content': '\n'.join(names)[:3900] or '(empty)'})
    details = []
    if warnings:
        details.append({'title': 'Scan warnings', 'content': '\n'.join(warnings[:20])[:3900]})
    return {'summary': [
        {'label': 'Selected paths', 'value': str(len(scanned))},
        {'label': 'Files/links', 'value': str(count_files)},
        {'label': 'Folders', 'value': str(sum(len(i['directories']) for i in scanned))},
        {'label': 'File sizes', 'value': readable_size(count_bytes)},
        *([{'label': 'Trash items',
            'value': str(sum(i['trash_count'] for i in scanned if i.get('finder_trash')))}]
          if any(i.get('finder_trash') for i in scanned) else []),
        {'label': 'Warnings', 'value': str(len(warnings))},
    ], 'columns': [
        {'key': 'label', 'label': 'Name'}, {'key': 'item', 'label': 'Target'}, {'key': 'files', 'label': 'Files'},
        {'key': 'folders', 'label': 'Folders'}, {'key': 'size', 'label': 'Size'},
    ], 'rows': rows[:100], 'row_ids': [str(i + 1) for i in range(len(scanned))],
        'row_details': row_details, 'details': details[:16], 'notice': 'Deletion is permanent.'}


def _open_parent(fd, relative_parent, known_dirs):
    """Open verified ancestors starting from the already verified root FD."""
    current = os.dup(fd)
    try:
        for offset, part in enumerate(relative_parent, 1):
            wanted = known_dirs[relative_parent[:offset]]
            following = os.open(part, OPEN_DIRECTORY, dir_fd=current)
            if identity(os.fstat(following), directory=True) != wanted:
                os.close(following)
                raise OSError('Parent directory was replaced after scan')
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


def execute_plan(scanned):
    """Only unlink snapshotted objects. Empty nested folders removed bottom-up."""
    total_files, total_bytes, total_dirs = 0, 0, 0
    errors = []
    for index, item in enumerate(scanned, 1):
        if item.get('finder_trash'):
            continue  # Handled by Finder only, never by direct file deletion.
        root = item['path']
        emit(f'[DELETE {index}/{len(scanned)}] {item.get("display_path", root)}')
        try:
            fd = _open_path_no_symlinks(root)
            try:
                if identity(os.fstat(fd), directory=True) != item['root_identity']:
                    raise OSError('Root directory identity changed; no deletion from this root')
                for parts, original, kind in item['files']:
                    parent = None
                    try:
                        parent = _open_parent(fd, parts[:-1], item['directories'])
                        now = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                        if identity(now) != original:
                            raise OSError('Item changed since preview')
                        os.unlink(parts[-1], dir_fd=parent)
                        total_files += 1
                        if kind == 'file':
                            total_bytes += original[3]
                        if total_files % 500 == 0:
                            emit(f'  removed {total_files} planned files/links so far...')
                    except OSError as exc:
                        errors.append(f'{root}/{"/".join(parts)}: {exc}')
                    finally:
                        if parent is not None:
                            os.close(parent)
                for parts, original in sorted(item['directories'].items(), key=lambda x: (-len(x[0]), x[0])):
                    parent = None
                    try:
                        parent = _open_parent(fd, parts[:-1], item['directories'])
                        now = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                        if identity(now, directory=True) != original:
                            raise OSError('Directory changed since preview')
                        os.rmdir(parts[-1], dir_fd=parent)  # fails if new/unplanned files appeared
                        total_dirs += 1
                    except OSError as exc:
                        errors.append(f'{root}/{"/".join(parts)}: {exc}')
                    finally:
                        if parent is not None:
                            os.close(parent)
            finally:
                os.close(fd)
        except OSError as exc:
            errors.append(f'No deletion in {root}: {exc}')
    return {'removed_files_and_links': total_files, 'removed_directories': total_dirs,
            'logical_file_bytes': total_bytes, 'errors': errors}


def main(params):
    selected = selected_directories(params)
    if not selected:
        emit('All cleanup paths disabled. Nothing to do.')
        return {'approved': False, 'reason': 'no targets'}

    scanned, warnings = scan_plan(selected)
    if not scanned:
        emit('No scannable directories. Nothing deleted.', warning=True)
        return {'approved': False, 'reason': 'no actionable targets', 'warnings': warnings}

    preview = make_preview(scanned, warnings)
    emit(f'PREVIEW: {sum(len(i["files"]) for i in scanned)} files/links, '
         f'{readable_size(sum(i["bytes"] for i in scanned))}; '
         f'warnings: {len(warnings)}')
    question = 'Permanently delete the selected items?'
    try:
        selected_ids = set(context.select_preview_rows(
            question, preview, title='Personal Disk Cleanup — Delete Plan', timeout=180))
    except ScriptSdkInteractionError:
        emit('Approval rejected/expired. Nothing deleted.')
        return {'approved': False, 'reason': 'rejected', 'warnings': warnings}
    selected_scanned = [item for index, item in enumerate(scanned, 1)
                        if str(index) in selected_ids]
    if not selected_scanned:
        emit('No items selected. Nothing deleted.')
        return {'approved': True, 'reason': 'no selected targets', 'warnings': warnings}
    result = execute_plan(selected_scanned)
    for item in selected_scanned:
        if item.get('finder_trash'):
            error = _empty_finder_trash(item['trash_count'])
            result['finder_trash_emptied'] = error is None
            if error:
                result['errors'].append(f'Finder Trash: {error}')
    result['approved'] = True
    result['warnings'] = warnings
    emit(f'FINISHED: {result["removed_files_and_links"]} files/links, '
         f'{result["removed_directories"]} directories; '
         f'{readable_size(result["logical_file_bytes"])} logical file bytes removed. '
         'Actual disk space reclaimed may differ (APFS clones/hard links).')
    for error in result['errors'][:30]:
        emit(error, warning=True)
    if len(result['errors']) > 30:
        emit(f'{len(result["errors"])-30} additional cleanup failures.', warning=True)
    return result


if __name__ == '__main__':
    main(kwargs)
