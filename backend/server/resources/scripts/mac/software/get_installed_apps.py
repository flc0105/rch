SCRIPT_METADATA = {
    "name": "mac/software/get_installed_apps",
    "display_name": "Installed Apps",
    "description": "List applications installed in standard macOS directories.",
    "platforms": ["mac"],
    "category": "Software",
    "params": []
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
    scanned_roots = 0
    for root in app_roots() if roots is None else roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            warnings.append(f'cannot read {root}: {exc}')
            continue
        scanned_roots += 1
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
    if warnings and scanned_roots == 0:
        return None, warnings
    return sorted(apps, key=lambda item: (item['name'].casefold(), item['path'])), warnings


def main():
    apps, warnings = collect()
    for warning in warnings:
        level = 'ERROR' if apps is None else 'WARNING'
        print(f'[APPS] {level}: {warning}', file=sys.stderr, flush=True)
    if apps is None:
        raise SystemExit(1)
    print(json.dumps(apps, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
