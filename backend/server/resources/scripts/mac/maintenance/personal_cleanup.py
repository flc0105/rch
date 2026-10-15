SCRIPT_METADATA = {
    "name": "mac/maintenance/personal_cleanup",
    "display_name": "Personal Cleanup",
    "description": "Preview and approve file deletion and package cache cleanup.",
    "platforms": ["mac"],
    "category": "Maintenance",
    "api_grants": ["interactions:request"],
    "params": [
        {"name": "cleanup_paths", "label": "Directories to clear (contents only)",
         "type": "path_list", "required": False,
         "description": "Each enabled row clears contents only, not the selected directory. Disabled rows are skipped. Deletion is permanent after Preview approval.",
         "default": [
             {"path": "/Users/flc/Work/Home/seeyona9/ApacheJetspeed/logs_sy", "enabled": True},
             {"path": "~/SeeyonLogs", "enabled": True},
             {"path": "~/NCCACHE", "enabled": True},
             {"path": "~/upload/files", "enabled": True},
             {"path": "~/Library/ScreenRecordings", "enabled": True},
         ]},
        {"name": "clean_npm_cache", "label": "Run npm cache clean --force", "type": "boolean",
         "description": "Clear npm's configured download cache with the official npm command after approval. Re-downloads may be needed.",
         "default": True},
        {"name": "clear_nvm_cache", "label": "Run nvm cache clear", "type": "boolean",
         "description": "Clear nvm's download cache using nvm.sh (nvm is a shell function, not a standalone executable).",
         "default": True},
        {"name": "prune_pnpm_store", "label": "Run pnpm store prune", "type": "boolean",
         "description": "Package-manager operation (not directory deletion): remove unused pnpm store packages after approval. The precise reclaimable size cannot be previewed.",
         "default": True},
    ],
}

# Deletion policy: NEVER remove a selected root, enter symlinked directories,
# traverse another filesystem, or delete an item that changed after scanning.
# The five directory presets are user approved. Editable additional paths must
# stay under home or an actual /Volumes/<name>/... mount. npm/nvm/pnpm cache
# operations use their package-manager commands only, never direct deletion.

import os
import shutil
import stat
import subprocess
from pathlib import Path

from client.runtime.sdk import context


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
        # Package caches must not re-enter the direct-delete path_list, including
        # from previously saved parameters that predate the command-based policy.
        manager_caches = (Path.home() / '.npm' / '_cacache',
                          Path.home() / '.nvm' / '.cache')
        if any(root == cache or cache in root.parents for cache in manager_caches):
            raise ValueError(f'Package cache must use npm/nvm command; remove path_list row: {root}')
        if any(root == previous or root in previous.parents or previous in root.parents
               for previous in chosen):
            raise ValueError(f'Duplicate/overlapping cleanup target: {root}')
        chosen.append(root)
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


def scan_plan(paths):
    scanned, warnings = [], []
    for index, root in enumerate(paths, 1):
        emit(f'[SCAN {index}/{len(paths)}] {root}')
        try:
            data = _scan_directory(root)
            scanned.append(data)
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


def _pnpm_info(enabled):
    if not enabled:
        return None, []
    exe = shutil.which('pnpm')
    if not exe:
        return None, ['pnpm not found in Client PATH; store prune will be skipped']
    exe = Path(exe).resolve()
    try:
        binary_id = identity(exe.stat())
        probe = subprocess.run([str(exe), 'store', 'path'], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=15, check=False)
        path_text = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ''
        label = path_text if probe.returncode == 0 else '(store path unavailable)'
        return {'executable': exe, 'identity': binary_id, 'store_path': label}, ([] if probe.returncode == 0 else
            [f'pnpm store path could not be determined: {probe.stderr.strip()[:200]}'])
    except (OSError, subprocess.TimeoutExpired, IndexError) as exc:
        return None, [f'pnpm store probe failed; prune skipped: {exc}']



def _cache_usage(directory):
    """Informational, read-only cache totals; commands decide what they reclaim."""
    if directory is None or not directory.is_dir() or directory.is_symlink():
        return None
    files, folders, total = 0, 0, 0
    try:
        base_device = directory.stat().st_dev
        stack = [directory]
        while stack:
            current = stack.pop()
            with os.scandir(current) as listing:
                for entry in listing:
                    info = entry.stat(follow_symlinks=False)
                    if info.st_dev != base_device:
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        folders += 1
                        stack.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        files += 1
                        total += info.st_size
        return {'files': files, 'folders': folders, 'bytes': total}
    except OSError:
        return None


def _npm_info(enabled):
    if not enabled:
        return None, []
    found = shutil.which('npm')
    if not found:
        return None, ['npm not found in Client PATH; npm cleanup skipped']
    try:
        executable = Path(found).resolve()
        binary_id = identity(executable.stat())
        # Read-only lookup: npm can use a custom cache path via npmrc or env.
        query = subprocess.run([str(executable), 'config', 'get', 'cache'],
                               stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=15, check=False)
        if query.returncode:
            raise OSError(f'npm cache location lookup exited {query.returncode}: {query.stderr.strip()[:160]}')
        value = query.stdout.strip()
        if not value or '\n' in value or '\x00' in value:
            raise OSError('npm returned an invalid cache path')
        cache_dir = Path(os.path.abspath(os.path.expanduser(value)))
        if cache_dir == Path('/') or cache_dir == Path.home():
            raise OSError(f'Unsafe npm cache root: {cache_dir}')
        content_dir = cache_dir / '_cacache'
        return {'executable': executable, 'identity': binary_id,
                'cache_dir': cache_dir, 'display_dir': content_dir,
                'usage': _cache_usage(content_dir)}, []
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, [f'npm cleanup skipped: {exc}']


def _nvm_info(enabled):
    if not enabled:
        return None, []
    try:
        raw_dir = os.environ.get('NVM_DIR') or str(Path.home() / '.nvm')
        if '\x00' in raw_dir:
            raise ValueError('NVM_DIR contains NUL')
        nvm_dir = Path(os.path.abspath(os.path.expanduser(raw_dir)))
        nvm_script = nvm_dir / 'nvm.sh'
        # nvm is a shell function. Never attempt to run it as a binary.
        if nvm_script.is_symlink() or not nvm_script.is_file():
            raise OSError(f'nvm.sh missing or symlinked: {nvm_script}')
        bash = shutil.which('bash')
        if not bash:
            raise OSError('bash not found in Client PATH')
        bash_path = Path(bash).resolve()
        return {'bash': bash_path, 'bash_id': identity(bash_path.stat()),
                'nvm_script': nvm_script, 'script_id': identity(nvm_script.stat()),
                'nvm_dir': nvm_dir, 'display_dir': nvm_dir / '.cache',
                'usage': _cache_usage(nvm_dir / '.cache')}, []
    except (OSError, ValueError) as exc:
        return None, [f'nvm cleanup skipped: {exc}']


def _package_row(name, info, operation):
    usage = info.get('usage')
    return {'item': f'{name} ({info["display_dir"]})',
            'files': str(usage['files']) if usage else '—',
            'folders': str(usage['folders']) if usage else '—',
            'size': ((readable_size(usage['bytes']) + ' (observed; not guaranteed reclaimable)')
                     if usage else 'Unknown reclaimable'),
            'operation': operation}


def _add_package_usages(actions):
    pnpm = actions['pnpm']
    if pnpm:
        store_path = Path(pnpm['store_path']) if pnpm['store_path'].startswith('/') else None
        pnpm['display_dir'] = pnpm['store_path']
        pnpm['usage'] = _cache_usage(store_path)


def _run_command(label, argv, *, timeout=600, env=None):
    try:
        emit(f'Running {label} ...')
        process = subprocess.run(argv, stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=timeout,
                                 check=False, env=env)
        for output in (process.stdout, process.stderr):
            if output.strip():
                emit(output.strip()[:3000], warning=process.returncode != 0)
        if process.returncode:
            raise OSError(f'{label} exited with status {process.returncode}')
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        emit(f'{label} failed: {exc}', warning=True)
        return False


def run_npm_clean(npm):
    if not npm:
        return None
    exe = npm['executable']
    try:
        if identity(exe.stat()) != npm['identity']:
            raise OSError('npm executable changed since Preview')
    except OSError as exc:
        emit(f'npm cleanup skipped: {exc}', warning=True)
        return False
    # Fix the cache target to the path displayed during Preview.
    return _run_command('npm cache clean --force',
                        [str(exe), 'cache', 'clean', '--force',
                         '--cache=' + str(npm['cache_dir'])])


def run_nvm_clear(nvm):
    if not nvm:
        return None
    try:
        if (identity(nvm['bash'].stat()) != nvm['bash_id'] or
                identity(nvm['nvm_script'].stat()) != nvm['script_id']):
            raise OSError('bash or nvm.sh changed after Preview')
    except OSError as exc:
        emit(f'nvm cache clear skipped: {exc}', warning=True)
        return False
    env = os.environ.copy()
    env['NVM_DIR'] = str(nvm['nvm_dir'])
    # The shell snippet is fixed; NVM_DIR is passed only via environment.
    return _run_command('nvm cache clear',
                        [str(nvm['bash']), '--noprofile', '--norc', '-c',
                         '. "$NVM_DIR/nvm.sh" && nvm cache clear'], env=env)


def make_preview(scanned, actions, warnings):
    count_files = sum(len(item['files']) for item in scanned)
    count_bytes = sum(item['bytes'] for item in scanned)
    rows = [{'item': str(item['path']), 'files': str(len(item['files'])),
             'folders': str(len(item['directories'])), 'size': readable_size(item['bytes']),
             'operation': 'Permanently clear contents'} for item in scanned]
    if actions['npm']:
        rows.append(_package_row('npm cache', actions['npm'], 'npm cache clean --force'))
    if actions['nvm']:
        rows.append(_package_row('nvm cache', actions['nvm'], 'nvm cache clear'))
    if actions['pnpm']:
        rows.append(_package_row('pnpm store', actions['pnpm'], 'pnpm store prune'))
    details = []
    for item in scanned[:10]:
        names = ['/'.join(row[0]) for row in item['files'][:30]]
        if len(item['files']) > 30:
            names.append(f'... and {len(item["files"])-30} additional files/links (in frozen plan)')
        details.append({'title': f'Files: {item["path"].name}', 'content': '\n'.join(names)[:3900] or '(empty)'})
    if warnings:
        details.append({'title': 'Scan warnings', 'content': '\n'.join(warnings[:20])[:3900]})
    return {'summary': [
        {'label': 'Selected directories', 'value': str(len(scanned))},
        {'label': 'Files/links (directory plan)', 'value': str(count_files)},
        {'label': 'Folders within directory roots', 'value': str(sum(len(i['directories']) for i in scanned))},
        {'label': 'Directory file sizes', 'value': readable_size(count_bytes)},
        {'label': 'Package manager commands', 'value': str(sum(bool(v) for v in actions.values()))},
        {'label': 'Warnings', 'value': str(len(warnings))},
    ], 'columns': [
        {'key': 'item', 'label': 'Target'}, {'key': 'files', 'label': 'Files'},
        {'key': 'folders', 'label': 'Folders'}, {'key': 'size', 'label': 'Size'},
        {'key': 'operation', 'label': 'Action'},
    ], 'rows': rows[:100], 'details': details[:16],
        'notice': ('PERMANENT deletion of the exact scanned directory file plan. Roots remain.')}


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
        root = item['path']
        emit(f'[DELETE {index}/{len(scanned)}] {root}')
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


def run_pnpm_prune(pnpm):
    if not pnpm:
        return None
    exe = pnpm['executable']
    try:
        if identity(exe.stat()) != pnpm['identity']:
            raise OSError('pnpm executable changed since Preview')
        emit(f'Running pnpm store prune using {exe} ...')
        process = subprocess.run([str(exe), 'store', 'prune'], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=600, check=False)
        for text in (process.stdout, process.stderr):
            if text.strip():
                emit(text.strip()[:3000], warning=process.returncode != 0)
        if process.returncode:
            raise OSError(f'pnpm store prune exited with status {process.returncode}')
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        emit(f'pnpm prune failed: {exc}', warning=True)
        return False


def main(params):
    selected = selected_directories(params)
    switches = {}
    for key in ('clean_npm_cache', 'clear_nvm_cache', 'prune_pnpm_store'):
        value = params.get(key, True)
        if type(value) is not bool:
            raise ValueError(f'{key} must be boolean')
        switches[key] = value
    if not selected and not any(switches.values()):
        emit('All cleanup paths and package-manager commands disabled. Nothing to do.')
        return {'approved': False, 'reason': 'no targets'}

    scanned, warnings = scan_plan(selected)
    npm, npm_warnings = _npm_info(switches['clean_npm_cache'])
    nvm, nvm_warnings = _nvm_info(switches['clear_nvm_cache'])
    pnpm, pnpm_warnings = _pnpm_info(switches['prune_pnpm_store'])
    actions = {'npm': npm, 'nvm': nvm, 'pnpm': pnpm}
    _add_package_usages(actions)
    warnings.extend(npm_warnings + nvm_warnings + pnpm_warnings)
    for message in npm_warnings + nvm_warnings + pnpm_warnings:
        emit(message, warning=True)
    if not scanned and not any(actions.values()):
        emit('No scannable directories or available package-manager commands. Nothing deleted.', warning=True)
        return {'approved': False, 'reason': 'no actionable targets', 'warnings': warnings}

    preview = make_preview(scanned, actions, warnings)
    emit(f'PREVIEW: {sum(len(i["files"]) for i in scanned)} files/links, '
         f'{readable_size(sum(i["bytes"] for i in scanned))}; '
         f'package commands: {", ".join(k for k, v in actions.items() if v) or "none"}; '
         f'warnings: {len(warnings)}')
    if not context.approve_preview('Permanently delete the scanned contents and run selected cache commands?',
                                   preview, title='Personal Disk Cleanup — Delete Plan', timeout=180):
        emit('Approval rejected/expired. Nothing deleted or cleared.')
        return {'approved': False, 'reason': 'rejected', 'warnings': warnings}
    result = execute_plan(scanned)
    result['npm_cleaned'] = run_npm_clean(npm)
    result['nvm_cleared'] = run_nvm_clear(nvm)
    result['pnpm_pruned'] = run_pnpm_prune(pnpm)
    result['approved'] = True
    result['warnings'] = warnings
    emit(f'FINISHED: {result["removed_files_and_links"]} files/links, '
         f'{result["removed_directories"]} directories; '
         f'{readable_size(result["logical_file_bytes"])} logical file bytes removed. '
         'Actual disk space reclaimed may differ (APFS clones/hard links; package-manager rules).')
    for error in result['errors'][:30]:
        emit(error, warning=True)
    if len(result['errors']) > 30:
        emit(f'{len(result["errors"])-30} additional cleanup failures.', warning=True)
    return result


if __name__ == '__main__':
    main(kwargs)
