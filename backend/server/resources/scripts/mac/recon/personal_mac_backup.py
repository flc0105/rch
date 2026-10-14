SCRIPT_METADATA = {
    "name": "macos/backup/personal_mac_backup",
    "display_name": "Personal Mac Backup to Artifact",
    "description": "Backup selected shell, browser, software inventory and Typora data into a dated ZIP artifact.",
    "platforms": ["macos"],
    "category": "Backup",
    "api_grants": ["scripts:read"],
    "params": [
        {"name": "include_zshrc", "label": "Zsh configuration", "type": "boolean", "default": True},
        {"name": "include_zsh_history", "label": "Zsh history", "type": "boolean", "default": True},
        {"name": "include_chrome_bookmarks", "label": "Chrome bookmarks", "type": "boolean", "default": True},
        {"name": "include_homebrew", "label": "Homebrew packages", "type": "boolean", "default": True},
        {"name": "include_installed_apps", "label": "Installed app inventory", "type": "boolean", "default": True},
        {"name": "include_typora", "label": "Typora documents", "type": "boolean", "default": True},
        {"name": "typora_directory", "label": "Typora directory", "type": "string",
         "required": False, "default": "/Users/flc/Documents/Typora",
         "description": "Directory to archive recursively; missing/unmounted volumes are warnings."},
    ],
}

import json
import os
import platform
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from client.runtime.sdk import artifact, context, scripts


SOURCES = (
    ("include_zshrc", "zshrc"),
    ("include_zsh_history", "zsh_history"),
    ("include_chrome_bookmarks", "chrome_bookmarks"),
    ("include_homebrew", "homebrew_packages"),
    ("include_installed_apps", "installed_apps"),
    ("include_typora", "typora_documents"),
)


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


def main(params):
    today = datetime.now().astimezone().strftime('%Y-%m-%d')
    timestamp = datetime.now(timezone.utc).isoformat()
    machine = re.sub(r'[^a-zA-Z0-9_-]', '-', platform.node())[:48].strip('-') or 'mac'
    backup_id = f'mac-personal-backup_{today}_{machine}'
    selected = [(flag, label) for flag, label in SOURCES if params.get(flag, True)]
    if not selected:
        raise ValueError('No backup items selected')

    records = []
    warnings = []
    counts = {label: {'files': 0, 'bytes': 0} for _flag, label in selected}
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

            for index, (flag, label) in enumerate(selected, 1):
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
                            'mac/recon/brew_packages', {},
                            f'software/homebrew_packages_{today}.json'),
                        'include_installed_apps': (
                            'mac/recon/get_installed_apps', {},
                            f'software/installed_apps_{today}.json'),
                    }[flag]
                    try:
                        result = scripts.run(script_name, script_params)
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

                elif flag == 'include_typora':
                    requested = str(params.get('typora_directory') or '/Users/flc/Documents/Typora')
                    folder = Path(requested).expanduser()
                    reason = missing_reason(folder)
                    if reason:
                        warn(label, reason)
                        continue
                    if not folder.is_dir():
                        warn(label, f'not a directory: {folder}')
                        continue
                    for root, dirnames, filenames in os.walk(
                        folder, topdown=True, followlinks=False,
                        onerror=lambda exc: warn(label, f'cannot scan directory: {exc}'),
                    ):
                        dirnames.sort()
                        filenames.sort()
                        kept = []
                        for item in dirnames:
                            child = Path(root) / item
                            if child.is_symlink():
                                warn(label, f'symbolic link directory skipped: {child}')
                            else:
                                kept.append(item)
                        dirnames[:] = kept
                        for filename in filenames:
                            filepath = Path(root) / filename
                            relative = filepath.relative_to(folder).as_posix()
                            add_file(label, f'documents/typora_{today}/{relative}', filepath)

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
                'selected': [label for _flag, label in selected],
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
        for _flag, label in selected:
            emit(f'  {label}: {counts[label]["files"]} files, '
                 f'{formatted_size(counts[label]["bytes"])}')
        emit(f'  TOTAL: {len(records)} files, {formatted_size(total)}; ZIP: {formatted_size(zip_size)}')
        emit(f'  WARNINGS: {len(warnings)}')
        return {'uploaded': True, 'artifact': saved, 'zip_name': output.name,
                'source_bytes': total, 'zip_bytes': zip_size,
                'counts': counts, 'warnings': warnings}


if __name__ == '__main__':
    main(kwargs)
