SCRIPT_METADATA = {
    "name": "mac/recon/personal_mac_backup",
    "display_name": "Personal Mac Backup to Artifact",
    "description": "Backup selected Mac settings, document folders and project folders into a dated ZIP artifact.",
    "platforms": ["macos"],
    "category": "Backup",
    "api_grants": ["scripts:read"],
    "params": [
        {"name": "include_zshrc", "label": "Zsh configuration", "type": "boolean", "default": True},
        {"name": "include_zsh_history", "label": "Zsh history", "type": "boolean", "default": True},
        {"name": "include_chrome_bookmarks", "label": "Chrome bookmarks", "type": "boolean", "default": True},
        {"name": "include_homebrew", "label": "Homebrew packages", "type": "boolean", "default": True},
        {"name": "include_installed_apps", "label": "Installed app inventory", "type": "boolean", "default": True},
        {"name": "documents", "label": "Documents", "type": "path_list", "required": False,
         "description": "Document directories. Add, disable or remove each path; hidden and macOS metadata excluded.",
         "default": [{"path": "/Users/flc/Documents/Typora", "enabled": True}]},
        {"name": "projects", "label": "Projects", "type": "path_list", "required": False,
         "description": "Source directories. Add, disable or remove each path; development dependencies excluded.",
         "default": [
             {"path": "/Users/flc/PycharmProjects/rch", "enabled": True},
             {"path": "/Volumes/T7/Projects/photo_library", "enabled": True},
             {"path": "/Users/flc/Projects/oh-my-wechat-personal", "enabled": True},
         ]},
    ],
}


# Centralized backup inclusion/exclusion policy (edit these lists to change the rules).
# Documents: only dot-prefixed files/directories and macOS resource-fork metadata.
# Projects: the same restrictions, plus the specifically selected development junk.
HIDDEN_PREFIXES = ('.',)  # Includes .git, .idea, .env, ._* AppleDouble files.
MACOS_METADATA_NAMES = frozenset({'__MACOSX', 'Icon\r'})
PROJECT_EXCLUDED_DIRS = frozenset({
    'venv', 'virtualenv', '__pycache__', 'site-packages',
    'node_modules', 'dist', 'tmp', 'temp', 'logs',
})
PROJECT_EXCLUDED_FILE_SUFFIXES = frozenset({
    '.pyc', '.pyo', '.class', '.log', '.tmp', '.swp', '.swo', '.out',
})
PROJECT_EXCLUDED_FILES = frozenset({'thumbs.db', 'desktop.ini'})

SOURCES = (
    ('include_zshrc', 'zshrc'),
    ('include_zsh_history', 'zsh_history'),
    ('include_chrome_bookmarks', 'chrome_bookmarks'),
    ('include_homebrew', 'homebrew_packages'),
    ('include_installed_apps', 'installed_apps'),
)

import json
import os
import platform
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from client.runtime.sdk import artifact, context, scripts




def excluded_entry(name, *, directory, project):
    # macOS resource forks are ._* sidecars; ZipFile does not save file xattrs.
    if name.startswith(HIDDEN_PREFIXES) or name in MACOS_METADATA_NAMES:
        return True
    if not project:
        return False
    lower = name.casefold()
    if directory:
        return lower in PROJECT_EXCLUDED_DIRS
    return (lower in PROJECT_EXCLUDED_FILES
            or Path(lower).suffix in PROJECT_EXCLUDED_FILE_SUFFIXES)



def emit(message, *, warning=False):
    context.progress(("[WARNING] " if warning else "[BACKUP] ") + message, status=0 if warning else 1)


def formatted_size(size):
    size = int(size)
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024
        if value < 1024 or unit == "TiB":
            return f"{value:.2f} {unit}"


def missing_reason(path):
    path = Path(path).expanduser()
    parts = path.parts
    if len(parts) >= 3 and parts[1] == 'Volumes':
        volume = Path('/', 'Volumes', parts[2])
        if not os.path.ismount(volume):
            return f"external volume not mounted: {volume}"
    if not path.exists():
        return f"missing path: {path}"
    return ''


def prepared_sources(params, today):
    """Build enabled backup items; names derive from paths, never fixed project mappings."""
    selected = [
        {'kind': 'setting', 'flag': flag, 'label': label}
        for flag, label in SOURCES if params.get(flag, True)
    ]
    for param_name, section, is_project in (
        ('documents', 'documents', False), ('projects', 'projects', True),
    ):
        # Script SDK populates missing defaults from SCRIPT_METADATA. Respect [] (all removed).
        spec = next(spec for spec in SCRIPT_METADATA['params'] if spec['name'] == param_name)
        entries = params.get(param_name, spec['default'])
        if not isinstance(entries, list):
            raise ValueError(f'{param_name} must be a path list')
        used_names = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
                raise ValueError(f'{param_name} path entries must be objects with a string path')
            if not isinstance(entry.get('enabled', True), bool):
                raise ValueError(f'{param_name} entry enabled must be boolean')
            if not entry.get('enabled', True) or not entry['path'].strip():
                continue
            folder = Path(entry['path'].strip()).expanduser()
            stem = re.sub(r'[^a-zA-Z0-9_-]+', '_', folder.name).strip('_-').lower() or 'folder'
            candidate = stem
            counter = 2
            while candidate in used_names:
                candidate = f'{stem}_{counter}'
                counter += 1
            used_names.add(candidate)
            selected.append({
                'kind': 'directory', 'label': f'{section}_{candidate}',
                'path': folder, 'prefix': f'{section}/{candidate}_{today}',
                'project': is_project,
            })
    return selected


def main(params):
    today = datetime.now().astimezone().strftime('%Y-%m-%d')
    timestamp = datetime.now(timezone.utc).isoformat()
    machine = re.sub(r'[^a-zA-Z0-9_-]', '-', platform.node())[:48].strip('-') or 'mac'
    backup_id = f'mac-personal-backup_{today}_{machine}'
    selected = prepared_sources(params, today)
    if not selected:
        raise ValueError('No backup items selected')

    records = []
    warnings = []
    counts = {item['label']: {'files': 0, 'bytes': 0} for item in selected}
    source_count = len(selected)
    emit(f'Start: {backup_id} | selected categories: {source_count}')

    def warn(label, message):
        detail = f'{label}: {message}'
        warnings.append(detail)
        emit(detail, warning=True)

    with tempfile.TemporaryDirectory(prefix='rch-mac-personal-backup-') as tempdir:
        output = Path(tempdir) / f'{backup_id}.zip'
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                             allowZip64=True) as archive:
            def add_bytes(label, arcname, data, source):
                archive_path = f'{backup_id}/{arcname}'
                archive.writestr(archive_path, data)
                nbytes = len(data)
                counts[label]['files'] += 1
                counts[label]['bytes'] += nbytes
                records.append({'group': label, 'name': arcname, 'source': str(source), 'size': nbytes})
                emit(f'  + {arcname} | {formatted_size(nbytes)}')

            def add_file(label, arcname, file_path, *, allow_link=False):
                try:
                    if file_path.is_symlink() and not allow_link:
                        warn(label, f'symbolic link skipped: {file_path}')
                        return
                    with open(file_path, 'rb') as handle, archive.open(f'{backup_id}/{arcname}', 'w') as sink:
                        nbytes = 0
                        while True:
                            block = handle.read(1024 * 1024)
                            if not block:
                                break
                            sink.write(block)
                            nbytes += len(block)
                    counts[label]['files'] += 1
                    counts[label]['bytes'] += nbytes
                    records.append({'group': label, 'name': arcname, 'source': str(file_path), 'size': nbytes})
                    emit(f'  + {arcname} | {formatted_size(nbytes)}')
                except (OSError, ValueError) as exc:
                    warn(label, f'file not backed up: {file_path}: {exc}')

            def add_directory(label, folder, archive_prefix, *, project=False):
                reason = missing_reason(folder)
                if reason:
                    warn(label, reason)
                    return
                if not folder.is_dir():
                    warn(label, f'not a directory: {folder}')
                    return
                for root, dirnames, filenames in os.walk(
                    folder, topdown=True, followlinks=False,
                    onerror=lambda exc: warn(label, f'cannot scan directory: {exc}'),
                ):
                    # Prune early: never descend into hidden, dependency or build trees.
                    kept = []
                    for dirname in sorted(dirnames):
                        if excluded_entry(dirname, directory=True, project=project):
                            continue
                        child = Path(root) / dirname
                        if child.is_symlink():
                            warn(label, f'symbolic link directory skipped: {child}')
                        else:
                            kept.append(dirname)
                    dirnames[:] = kept
                    for filename in sorted(filenames):
                        if excluded_entry(filename, directory=False, project=project):
                            continue
                        filepath = Path(root) / filename
                        relative = filepath.relative_to(folder).as_posix()
                        if not filepath.is_file() and not filepath.is_symlink():
                            warn(label, f'not a regular file: {filepath}')
                            continue
                        add_file(label, f'{archive_prefix}/{relative}', filepath)

            for index, item in enumerate(selected, 1):
                label = item['label']
                flag = item.get('flag', '')
                emit(f'[{index}/{source_count}] {label}')
                if flag in ('include_zshrc', 'include_zsh_history'):
                    source = Path.home() / ('.zshrc' if flag == 'include_zshrc' else '.zsh_history')
                    reason = missing_reason(source)
                    if reason:
                        warn(label, reason)
                    elif not source.is_file():
                        warn(label, f'not a regular file: {source}')
                    else:
                        add_file(label, f'shell/{label}_{today}.txt', source, allow_link=True)

                elif flag in ('include_chrome_bookmarks', 'include_homebrew', 'include_installed_apps'):
                    script_name, script_params, arcname = {
                        'include_chrome_bookmarks': (
                            'common/browser/get_chromium_bookmarks', {'browser': 'chrome'},
                            f'browser/chrome_bookmarks_{today}.json'),
                        'include_homebrew': (
                            'mac/recon/backup_brew_packages', {},
                            f'software/homebrew_packages_{today}.json'),
                        'include_installed_apps': (
                            'mac/recon/backup_installed_apps', {},
                            f'software/installed_apps_{today}.json'),
                    }[flag]
                    try:
                        emit(f'  Running collector: {script_name} (waiting for result)')
                        result = scripts.run(script_name, script_params)
                        if result.ok and result.stderr.strip():
                            warn(label, f'collector fallback notice: {result.stderr.strip()[:400]}')
                        if not result.ok:
                            warn(label, f'subscript failed: {script_name}: {(result.stderr or result.stdout).strip()[:400]}')
                            continue
                        value = result.json()
                        if isinstance(value, dict) and 'error' in value:
                            warn(label, f'{script_name}: {value["error"]}')
                            continue
                        normalized = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
                        add_bytes(label, arcname, normalized, f'script:{script_name}')
                    except Exception as exc:
                        warn(label, f'subscript unavailable: {script_name}: {exc}')

                elif item['kind'] == 'directory':
                    add_directory(label, item['path'], item['prefix'], project=item['project'])

                emit(f'[{index}/{source_count}] completed {label}: '
                     f'{counts[label]["files"]} files, {formatted_size(counts[label]["bytes"])}')

            if not records:
                emit('No readable items were found; no empty archive will be uploaded.', warning=True)
                for issue in warnings:
                    emit(f'  {issue}')
                return {'uploaded': False, 'warnings': warnings}

            manifest = {
                'backup_name': backup_id,
                'exported_at_utc': timestamp,
                'selected': [item['label'] for item in selected],
                'counts': counts,
                'files': records,
                'warnings': warnings,
            }
            manifest_name = f'manifest/backup_manifest_{today}.json'
            archive.writestr(f'{backup_id}/{manifest_name}',
                             json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')

        total = sum(item['size'] for item in records)
        zip_size = output.stat().st_size
        emit(f'ZIP ready: {output.name} | {len(records)} files | '
             f'{formatted_size(total)} original / {formatted_size(zip_size)} ZIP')
        emit('Uploading to Artifact (shared_files)...')
        saved = artifact.save(str(output), type='shared_files', category='script', extra={
            'purpose': 'mac_personal_backup', 'export_date': today,
        })
        emit(f'Uploaded: artifact_id={saved.get("artifact_id", "")}')
        emit('Backup summary:')
        for item in selected:
            label = item['label']
            emit(f'  {label}: {counts[label]["files"]} files, '
                 f'{formatted_size(counts[label]["bytes"])}')
        emit(f'  TOTAL: {len(records)} files, {formatted_size(total)}; ZIP: {formatted_size(zip_size)}')
        emit(f'  WARNINGS: {len(warnings)}')
        return {'uploaded': True, 'artifact': saved, 'zip_name': output.name,
                'source_bytes': total, 'zip_bytes': zip_size,
                'counts': counts, 'warnings': warnings}


if __name__ == '__main__':
    main(kwargs)
