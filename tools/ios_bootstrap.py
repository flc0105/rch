"""Bootstrap an RCH source Bundle inside iOS/Pythonista, without subprocess.

Edit WEB_HOST / WEB_PORT / SERVER_HOST / SERVER_PORT below, then execute
this script in the target iOS Python environment. Requires Python 3.10+;
uses only the Python standard library.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import traceback
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


# --- Connection settings: adjust to the address reachable from the iOS device ---
WEB_HOST = '192.168.2.47'
WEB_PORT = 8085
WEB_SCHEME = 'http'
SERVER_HOST = WEB_HOST
SERVER_PORT = 9999
# ------------------------------------------------------------------------------

BASE_URL = f'{WEB_SCHEME}://{WEB_HOST}:{WEB_PORT}'
BUNDLE_ROOT = Path.home() / 'Documents' / 'client_bundle'
DOWNLOADS_DIR = BUNDLE_ROOT / 'downloads'
RELEASES_DIR = BUNDLE_ROOT / 'releases'
_SAFE_NAME = re.compile(r'[A-Za-z0-9._-]+\Z')
_SHA256 = re.compile(r'[0-9a-fA-F]{64}\Z')


def log(message):
    print(f'[bootstrap] {message}', flush=True)


def _metadata_name(value, label):
    if not isinstance(value, str) or not _SAFE_NAME.fullmatch(value) or value in ('.', '..'):
        raise ValueError(f'Invalid {label} in build response')
    return value


def build_bundle():
    payload = {
        'server_host': SERVER_HOST,
        'server_port': SERVER_PORT,
        'server_web_scheme': WEB_SCHEME,
        'server_web_host': WEB_HOST,
        'web_port': WEB_PORT,
        'target_os': 'bundle',
        'builder': 'bundle',
        'target_arch': '',
        'source': 'ios_bootstrap',
    }
    request = Request(
        f'{BASE_URL}/api/agent/build',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    log('Requesting Bundle build')
    with urlopen(request, timeout=300) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get('code') != 0:
        raise RuntimeError('Bundle build failed: ' + str(result.get('message') if isinstance(result, dict) else result))
    data = result.get('data')
    if not isinstance(data, dict):
        raise ValueError('Bundle build response has no data object')
    return data


def download_bundle(meta):
    filename = _metadata_name(meta.get('file_name'), 'file_name')
    version = _metadata_name(meta.get('build_version'), 'build_version')
    expected_hash = meta.get('sha256')
    if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
        raise ValueError('Bundle build response has no valid sha256')
    if not filename.endswith('.zip'):
        raise ValueError('Expected a Bundle ZIP file')

    relative_url = meta.get('download_url')
    if not isinstance(relative_url, str) or not relative_url:
        raise ValueError('Bundle build response has no download_url')
    url = urljoin(BASE_URL + '/', relative_url)
    origin = urlsplit(BASE_URL)
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc) or not parsed.path.startswith('/api/agent/download/'):
        raise ValueError('Bundle download URL is outside the configured Server')

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS_DIR / filename
    partial = DOWNLOADS_DIR / (filename + '.part')
    digest = hashlib.sha256()
    try:
        log(f'Downloading Bundle: {filename}')
        with urlopen(url, timeout=300) as response, partial.open('wb') as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest().lower() != expected_hash.lower():
            raise ValueError('Bundle SHA-256 verification failed')
        os.replace(partial, dest)
    finally:
        if partial.exists():
            partial.unlink()
    log('Bundle SHA-256 verified')
    return dest, version


def _validate_archive(archive):
    if archive.testzip() is not None:
        raise ValueError('Bundle ZIP CRC verification failed')
    seen = set()
    for member in archive.infolist():
        name = member.filename
        parts = PurePosixPath(name).parts
        mode = member.external_attr >> 16
        if (not name or name.startswith('/') or '\\' in name or '..' in parts
                or not parts or stat.S_IFMT(mode) == stat.S_IFLNK):
            raise ValueError(f'Unsafe Bundle ZIP member: {name!r}')
        if name.rstrip('/') in seen:
            raise ValueError('Duplicate Bundle ZIP member: ' + name)
        seen.add(name.rstrip('/'))


def install_bundle(archive_path, version):
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    release = RELEASES_DIR / _metadata_name(version, 'build_version')
    if release.exists() or release.is_symlink():
        # Never overwrite an installed Release that another Client may be using.
        raise FileExistsError(f'Bundle Release already exists: {release}')

    staging = Path(tempfile.mkdtemp(prefix='.ios-bootstrap-', dir=str(RELEASES_DIR)))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _validate_archive(archive)
            archive.extractall(staging)
        if not (staging / 'rchclient.py').is_file():
            raise FileNotFoundError('Bundle does not contain rchclient.py')
        os.rename(staging, release)
        log(f'Bundle installed: {release}')
        return release
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def start_client(release):
    entry = release / 'rchclient.py'
    if not entry.is_file():
        raise FileNotFoundError(entry)

    def runner():
        # iOS cannot create detached child processes. The Client therefore runs
        # within the same Python interpreter, on a non-daemon thread.
        import runpy
        previous_cwd = Path.cwd()
        previous_argv = sys.argv[:]
        release_text = str(release)
        added_to_path = release_text not in sys.path
        try:
            os.chdir(release)
            if added_to_path:
                sys.path.insert(0, release_text)
            sys.argv = [str(entry)]
            log(f'Starting Client in current interpreter: {entry}')
            runpy.run_path(str(entry), run_name='__main__')
        except BaseException:
            log('Client exited with an error:')
            traceback.print_exc()
        finally:
            sys.argv = previous_argv
            os.chdir(previous_cwd)
            if added_to_path and release_text in sys.path:
                sys.path.remove(release_text)

    thread = threading.Thread(target=runner, name='rchclient-main', daemon=False)
    thread.start()
    return thread


def main():
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required')
    log(f'Server Web: {BASE_URL}; Socket: {SERVER_HOST}:{SERVER_PORT}')
    meta = build_bundle()
    archive, version = download_bundle(meta)
    release = install_bundle(archive, version)
    start_client(release)
    log('Handoff complete; bootstrap main thread returns (Client thread remains active)')


if __name__ == '__main__':
    main()
