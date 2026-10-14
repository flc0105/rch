SCRIPT_METADATA = {
    "name": "mac/recon/backup_installed_apps",
    "display_name": "Installed App Inventory (Backup)",
    "description": "Collect macOS application names, bundle IDs and versions without launching plutil for each app; JSON-only stdout.",
    "platforms": ["macos"],
    "category": "Backup",
    "params": [],
}

import json
import plistlib
import sys
from pathlib import Path


def app_roots():
    home = Path.home()
    return (
        Path('/Applications'),
        Path('/Applications/Utilities'),
        Path('/System/Applications'),
        Path('/System/Applications/Utilities'),
        home / 'Applications',
    )


def collect(roots=None):
    apps = []
    warnings = []
    seen = set()
    for root in app_roots() if roots is None else roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            warnings.append(f'cannot read {root}: {exc}')
            continue
        for app in entries:
            if app.suffix.lower() != '.app' or app.is_symlink() or not app.is_dir():
                continue
            # Retain inventory semantics: one entry per installed application name.
            dedup_key = app.stem.casefold()
            if dedup_key in seen:
                continue
            details = {
                'name': app.stem,
                'path': str(app),
                'location': str(root),
                'bundle_id': '',
                'version': '',
            }
            info_path = app / 'Contents' / 'Info.plist'
            if info_path.is_file():
                try:
                    with info_path.open('rb') as handle:
                        info = plistlib.load(handle)
                    if isinstance(info, dict):
                        details['bundle_id'] = str(info.get('CFBundleIdentifier') or '')
                        details['version'] = str(info.get('CFBundleShortVersionString') or '')
                except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as exc:
                    warnings.append(f'cannot read {info_path}: {exc}')
            seen.add(dedup_key)
            apps.append(details)
    return sorted(apps, key=lambda item: (item['name'].casefold(), item['path'])), warnings


def main():
    apps, warnings = collect()
    for warning in warnings:
        print(f'[BACKUP APPS] WARNING: {warning}', file=sys.stderr, flush=True)
    print(json.dumps(apps, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
