SCRIPT_METADATA = {
    "name": "mac/recon/backup_brew_packages",
    "display_name": "Homebrew Inventory (Backup)",
    "description": "Collect installed formulae and casks using bounded, lightweight brew list commands; JSON-only stdout.",
    "platforms": ["macos"],
    "category": "Backup",
    "params": [],
}

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


COMMAND_TIMEOUT_SECONDS = 12


def find_brew():
    """Also locate Homebrew when a background Client has a minimal PATH."""
    found = shutil.which('brew')
    if found:
        return found
    for candidate in ('/opt/homebrew/bin/brew', '/usr/local/bin/brew'):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def record(kind, token, versions):
    """Use the inventory field names already used in backup ZIPs."""
    return {
        'type': kind,
        'token': token,
        'name': token,
        'tap': '',
        'installed_ver': versions,
        'desc': '',
        'homepage': '',
        'url': '',
        'depends_on': [],
        'installed_time': '',
    }


def read_installed(brew, kind):
    args = [brew, 'list', '--formula' if kind == 'formula' else '--cask', '--versions']
    environment = os.environ.copy()
    environment.update(HOMEBREW_NO_AUTO_UPDATE='1', HOMEBREW_NO_ANALYTICS='1')
    try:
        result = subprocess.run(
            args, text=True, capture_output=True, timeout=COMMAND_TIMEOUT_SECONDS,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return None, f'{kind} inventory timed out after {COMMAND_TIMEOUT_SECONDS}s'
    except OSError as exc:
        return None, f'{kind} inventory cannot start: {exc}'
    if result.returncode:
        reason = (result.stderr or result.stdout).strip()[:300]
        return None, f'{kind} inventory failed ({result.returncode}): {reason}'

    values = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if not fields:
            continue
        values.append(record(kind, fields[0], fields[1] if len(fields) > 1 else ''))
    return values, ''


def collect():
    brew = find_brew()
    if not brew:
        return None, ['Homebrew executable not found']
    collected = []
    warnings = []
    successful = 0
    for kind in ('formula', 'cask'):
        entries, error = read_installed(brew, kind)
        if error:
            warnings.append(error)
        else:
            successful += 1
            collected.extend(entries)
    if not successful:
        return None, warnings
    collected.sort(key=lambda item: (item['type'], item['token'].casefold()))
    return collected, warnings


def main():
    rows, warnings = collect()
    for warning in warnings:
        print(f'[BACKUP BREW] WARNING: {warning}', file=sys.stderr, flush=True)
    if rows is None:
        print(json.dumps({'error': '; '.join(warnings)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
