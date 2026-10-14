SCRIPT_METADATA = {
    "name": "mac/recon/personal_mac_backup_preview",
    "display_name": "Personal Mac Backup — Preview and Approval",
    "description": "Scan every enabled backup item, display item sizes and counts, obtain approval, then upload the verified snapshot.",
    "platforms": ["macos"],
    "category": "Backup",
    "api_grants": ["scripts:read", "interactions:request"],
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




def _file_snapshot(file_path):
    """Stable identity of a regular file; no symlinks or redirected parents accepted."""
    info = file_path.stat(follow_symlinks=False)
    if not file_path.is_file() or file_path.is_symlink():
        raise OSError(f'not a regular nonsymlink file: {file_path}')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def scan_plan(selected, today):
    """Preview once. Execute only these immutable, individually verified members."""
    plan = []
    warnings = []
    counts = {item['label']: {'files': 0, 'bytes': 0} for item in selected}

    def warn(label, text):
        message = f'{label}: {text}'
        warnings.append(message)
        emit(message, warning=True)

    def include_file(label, path, arcname):
        try:
            identity = _file_snapshot(path)
        except OSError as exc:
            warn(label, f'cannot preview file: {path}: {exc}')
            return
        plan.append({'label': label, 'source': path, 'name': arcname,
                     'identity': identity, 'size': identity[2]})
        counts[label]['files'] += 1
        counts[label]['bytes'] += identity[2]

    for index, item in enumerate(selected, 1):
        label, flag = item['label'], item.get('flag', '')
        emit(f'[SCAN {index}/{len(selected)}] {label}')
        if flag in ('include_zshrc', 'include_zsh_history'):
            path = Path.home() / ('.zshrc' if flag == 'include_zshrc' else '.zsh_history')
            reason = missing_reason(path)
            if reason:
                warn(label, reason)
            else:
                include_file(label, path, f'shell/{label}_{today}.txt')
        elif flag in ('include_chrome_bookmarks', 'include_homebrew', 'include_installed_apps'):
            script_name, params, arcname = {
                'include_chrome_bookmarks': ('common/browser/get_chromium_bookmarks', {'browser': 'chrome'},
                                             f'browser/chrome_bookmarks_{today}.json'),
                'include_homebrew': ('mac/recon/backup_brew_packages', {},
                                     f'software/homebrew_packages_{today}.json'),
                'include_installed_apps': ('mac/recon/backup_installed_apps', {},
                                           f'software/installed_apps_{today}.json'),
            }[flag]
            try:
                emit(f'  collecting {script_name} for preview')
                result = scripts.run(script_name, params)
                if not result.ok:
                    warn(label, f'collector failed: {(result.stderr or result.stdout).strip()[:300]}')
                    continue
                data = result.json()
                if isinstance(data, dict) and data.get('error'):
                    warn(label, f'collector error: {data["error"]}')
                    continue
                content = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
                plan.append({'label': label, 'source': f'script:{script_name}',
                             'name': arcname, 'payload': content, 'size': len(content)})
                counts[label]['files'] += 1
                counts[label]['bytes'] += len(content)
                if result.stderr.strip():
                    warn(label, f'collector notice: {result.stderr.strip()[:300]}')
            except Exception as exc:
                warn(label, f'collector unavailable: {exc}')
        elif item['kind'] == 'directory':
            folder = item['path']
            reason = missing_reason(folder)
            if reason:
                warn(label, reason)
                continue
            if not folder.is_dir() or folder.is_symlink():
                warn(label, f'not a regular directory: {folder}')
                continue
            for root, dirnames, filenames in os.walk(folder, topdown=True, followlinks=False,
                    onerror=lambda exc: warn(label, f'directory scan error: {exc}')):
                dirnames[:] = [name for name in sorted(dirnames)
                               if not excluded_entry(name, directory=True, project=item['project'])
                               and not (Path(root) / name).is_symlink()]
                for filename in sorted(filenames):
                    if excluded_entry(filename, directory=False, project=item['project']):
                        continue
                    path = Path(root) / filename
                    relative = path.relative_to(folder).as_posix()
                    include_file(label, path, f'{item["prefix"]}/{relative}')
        emit(f'[SCAN {index}/{len(selected)}] {label}: '
             f'{counts[label]["files"]} files, {formatted_size(counts[label]["bytes"])}')

    return plan, counts, warnings


def main(params):
    today = datetime.now().astimezone().strftime('%Y-%m-%d')
    stamp = datetime.now(timezone.utc).isoformat()
    machine = re.sub(r'[^a-zA-Z0-9_-]', '-', platform.node())[:48].strip('-') or 'mac'
    backup_id = f'mac-personal-backup_{today}_{machine}'
    selected = prepared_sources(params, today)
    if not selected:
        raise ValueError('No backup items selected')

    emit(f'Preview scanning {len(selected)} selected items...')
    plan, counts, warnings = scan_plan(selected, today)
    file_count, size_total = len(plan), sum(row['size'] for row in plan)
    lines = [f'{item["label"]}: {counts[item["label"]]["files"]} files, '
             f'{formatted_size(counts[item["label"]]["bytes"])}' for item in selected]
    emit('PREVIEW — NO ARCHIVE OR UPLOAD YET:\n' + '\n'.join(lines))
    emit(f'TOTAL: {file_count} files, {formatted_size(size_total)}; warnings: {len(warnings)}')
    if not plan:
        emit('Nothing to back up; no archive created.', warning=True)
        return {'uploaded': False, 'warnings': warnings}

    summary = (f'Back up {file_count} previously scanned files ({formatted_size(size_total)}) '
               f'from {len(selected)} selected items and upload to Artifact?\n\n'
               + '\n'.join(lines))
    if not context.confirm(summary, title='Approve personal Mac backup', timeout=180):
        emit('Not approved — no ZIP was created or uploaded.')
        return {'uploaded': False, 'reason': 'rejected', 'warnings': warnings}

    records = []
    actual_counts = {item['label']: {'files': 0, 'bytes': 0} for item in selected}
    with tempfile.TemporaryDirectory(prefix='rch-mac-backup-preview-') as tmp:
        output = Path(tmp) / f'{backup_id}.zip'
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                             allowZip64=True) as archive:
            for index, item in enumerate(plan, 1):
                label = item['label']
                source = item['source']
                if 'payload' in item:
                    content = item['payload']
                    archive.writestr(f'{backup_id}/{item["name"]}', content)
                    length = len(content)
                else:
                    try:
                        if _file_snapshot(source) != item['identity']:
                            raise OSError('file changed since approval')
                        with source.open('rb') as inp, archive.open(f'{backup_id}/{item["name"]}', 'w') as dest:
                            length = 0
                            while True:
                                block = inp.read(1024 * 1024)
                                if not block:
                                    break
                                dest.write(block)
                                length += len(block)
                        if _file_snapshot(source) != item['identity']:
                            warnings.append(f'{label}: source changed during copy: {source}')
                            emit(f'source changed during copy: {source}', warning=True)
                    except (OSError, ValueError) as exc:
                        warnings.append(f'{label}: skipped changed/unreadable source {source}: {exc}')
                        emit(f'skipped: {source}: {exc}', warning=True)
                        continue
                records.append({'group': label, 'name': item['name'], 'source': str(source), 'size': length})
                actual_counts[label]['files'] += 1
                actual_counts[label]['bytes'] += length
                emit(f'[ZIP {index}/{len(plan)}] + {item["name"]}: {formatted_size(length)}')
            if not records:
                emit('No verified files remain; no empty ZIP upload.', warning=True)
                return {'uploaded': False, 'warnings': warnings}
            manifest = {'backup_name': backup_id, 'exported_at_utc': stamp,
                        'selected': [item['label'] for item in selected],
                        'preview_counts': counts, 'counts': actual_counts,
                        'files': records, 'warnings': warnings}
            archive.writestr(f'{backup_id}/manifest/backup_manifest_{today}.json',
                             json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
        zip_size = output.stat().st_size
        emit(f'Approved ZIP: {output.name} ({formatted_size(zip_size)})')
        saved = artifact.save(str(output), type='shared_files', category='script',
                              extra={'purpose': 'mac_personal_backup', 'export_date': today})
        emit(f'Artifact uploaded: {saved.get("artifact_id", "")}')
        for group, count in actual_counts.items():
            emit(f'  {group}: {count["files"]} files, {formatted_size(count["bytes"])}')
        return {'uploaded': True, 'artifact': saved, 'zip_name': output.name,
                'source_bytes': sum(row['size'] for row in records), 'zip_bytes': zip_size,
                'counts': actual_counts, 'warnings': warnings}


if __name__ == '__main__':
    main(kwargs)
