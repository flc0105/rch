from core.transfer_settings import FileTransferMode
"""Common file commands available on every Python Client."""
import fnmatch
import http.client
import os
import re
import ssl
import stat
import tempfile
import time
from pathlib import PureWindowsPath
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from client.config import runtime_config
from client.commands.acmd.decorators import argument_command
from client.commands.acmd.standalone.zip import zip
from client.commands.acmd.standalone.unzip import unzip
from client.commands.runtime.interrupts import cancel_policy
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.filesystem.conflict_policy import UPLOAD_FILE_POLICIES, commit_download_file
from core.command_completion.models import CompletionSpec
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.formatting import format_bytes


DOWNLOAD_SPEC = ArgumentCommandSpec(
    name='download',
    description='Download a file from the client',
    options=[
        ArgumentOptionSpec('path', 'str', default='', positional_index=0,
                           completion=CompletionSpec('filesystem', ('file', 'directory')),
                           help_text='File to download'),
        ArgumentOptionSpec('name', 'str', default='', allow_empty=False, help_text='Saved filename'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd download file.zip --name new.zip'],
)

FIND_SPEC = ArgumentCommandSpec(
    name='find',
    description='Find files and directories recursively by keyword or wildcard',
    options=[
        ArgumentOptionSpec('path', 'str', default='.', positional_index=0,
                           completion=CompletionSpec('filesystem', ('directory',)),
                           help_text='Search directory (default: current directory)'),
        ArgumentOptionSpec('keyword', 'str', required=True, allow_empty=False,
                           help_text='Case-insensitive name substring or wildcard (e.g. *.jpg)'),
        ArgumentOptionSpec('type', 'str', default='', help_text='Match only file or dir'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd find --keyword article', 'acmd find ./photos --keyword "img_*.png"'],
)

WGET_SPEC = ArgumentCommandSpec(
    name='wget',
    description='Download a URL to a local file',
    options=[
        ArgumentOptionSpec('url', 'str', required=True, allow_empty=False, positional_index=0, help_text='HTTP, HTTPS or FTP URL'),
        ArgumentOptionSpec('output', 'str', default='', allow_empty=True, alias='o',
                           completion=CompletionSpec('filesystem', ('file', 'directory')),
                           help_text='Output file path or existing directory'),
        ArgumentOptionSpec('conflict', 'str', default='replace',
                           help_text='If the destination exists: stop, replace or keep_both'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd wget https://example.com/report.pdf -o ./report.pdf'],
)


FILE_SHRED_SPEC = ArgumentCommandSpec(
    name='file_shred',
    description='Overwrite and delete a file',
    options=[
        ArgumentOptionSpec('path', 'str', required=True, allow_empty=False, positional_index=0,
                           completion=CompletionSpec('filesystem', ('file',)), help_text='File to overwrite'),
        ArgumentOptionSpec('passes', 'int', default=3, help_text='Number of overwrite passes (default: 3)'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd file_shred ./sample.txt --passes 1'],
)


def _wget_tls_context():
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        pass
    else:
        bundle = certifi.where()
        if os.path.isfile(bundle):
            context.load_verify_locations(cafile=bundle)

    configured = os.environ.get('REQUESTS_CA_BUNDLE') or os.environ.get('CURL_CA_BUNDLE')
    if configured:
        if os.path.isdir(configured):
            context.load_verify_locations(capath=configured)
        else:
            context.load_verify_locations(cafile=configured)
    return context




@argument_command('download', spec=DOWNLOAD_SPEC, output='stream')
@cancel_policy('cooperative')
def download(self, args_dict, payload=None):
    filename = args_dict['path']
    if not filename.strip():
        return 0, 'Usage: acmd download <file> [--name <filename>]'
    name = args_dict['name']
    if name and (name in ('.', '..') or any(char in name for char in '/\\\x00')):
        return 0, '--name must be a filename'
    try:
        self._set_cancel_policy('cooperative')
        self._checkpoint()
        if runtime_config.FILE_TRANSFER_MODE == FileTransferMode.HTTP_SIMPLE.value:
            self._set_cancel_policy(
                mode='none',
                message='Current file transfer mode is http_simple; download cancellation is not supported')
        file_path = self.path_resolver.require_existing_file(filename)
        source_command = (payload or {}).get('raw') or f'acmd download {filename}'
        return self.http_file_transfer_service.upload_single_file_to_server_result(
            file_path,
            category='downloads',
            upload_name=name,
            extra={'saved_from': 'client_command', 'source_command': source_command},
        )
    except (CommandCancelledError, CommandTimeoutError):
        raise
    except Exception as exc:
        return 0, f'Failed to download file: {exc}'
@argument_command('file_shred', spec=FILE_SHRED_SPEC, output='stream')
@cancel_policy('cooperative')
def file_shred(self, args_dict):
    passes = args_dict['passes']
    if passes < 1:
        return 0, '--passes must be a positive integer'

    self._set_cancel_policy('cooperative')
    try:
        self._checkpoint()
        target = self.path_resolver.resolve_target_path(args_dict['path'])
        before = os.lstat(target)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink > 1:
            return 0, 'Select a regular file without symbolic links or additional hard links.'

        open_flags = getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        with open(target, 'r+b', opener=lambda path, flags: os.open(path, flags | open_flags)) as stream:
            original = os.fstat(stream.fileno())
            if (not stat.S_ISREG(original.st_mode) or original.st_nlink > 1
                    or not os.path.samestat(before, original)):
                return 0, 'File changed before it could be overwritten.'
            size = original.st_size
            self.emit_chunk(f'Shredding {target} ({format_bytes(size)})')
            chunk_size = 1024 * 1024
            for index in range(passes):
                self._checkpoint()
                pattern = index % 3
                stream.seek(0)
                remaining = size
                while remaining:
                    self._checkpoint()
                    count = min(remaining, chunk_size)
                    data = os.urandom(count) if pattern == 2 else bytes([255 * pattern]) * count
                    stream.write(data)
                    remaining -= count
                stream.flush()
                os.fsync(stream.fileno())

        self._checkpoint()
        current = os.lstat(target)
        if (not os.path.samestat(original, current) or not stat.S_ISREG(current.st_mode)
                or current.st_nlink > 1 or current.st_size != size):
            return 0, 'File changed during overwrite and was not deleted.'
        os.unlink(target)
        return 1, f'File overwritten and deleted: {target}'
    except (CommandCancelledError, CommandTimeoutError):
        raise
    except OSError as exc:
        return 0, f'Failed to shred file: {exc}'
@argument_command('find', spec=FIND_SPEC)
@cancel_policy('cooperative')
def find(self, args_dict):
    self._set_cancel_policy('cooperative')
    match_type = args_dict.get('type') or ''
    if match_type and match_type not in ('file', 'dir'):
        return 0, '--type must be file or dir'
    root = self.path_resolver.require_existing_directory(args_dict['path'])
    keyword = args_dict['keyword'].strip().casefold()
    glob = any(char in keyword for char in '*?[')
    matches = []

    for directory, dirs, files in self._iter_checked(os.walk(root)):
        dirs.sort(key=str.casefold)
        names = {'file': files, 'dir': dirs}[match_type] if match_type else dirs + files
        for name in self._iter_checked(sorted(names, key=str.casefold), check_interval=64):
            normalized = name.casefold()
            matched = fnmatch.fnmatchcase(normalized, keyword) if glob else keyword in normalized
            if matched:
                path = os.path.join(directory, name)
                if match_type != 'file' or os.path.isfile(path):
                    matches.append(path)

    return 1, '\n'.join(matches) if matches else 'No matches found.'
@argument_command('wget', spec=WGET_SPEC, output='stream')
@cancel_policy('cooperative')
def wget(self, args_dict):
    self._set_cancel_policy('cooperative')
    url = args_dict['url'].strip()
    output = args_dict['output'].strip()
    conflict = args_dict.get('conflict', 'replace')
    if conflict not in UPLOAD_FILE_POLICIES:
        return 0, '--conflict must be stop, replace or keep_both'
    staged_path = None
    target = ''
    try:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https', 'ftp') or not parts.hostname:
            return 0, 'Enter a valid HTTP, HTTPS or FTP URL.'
        self._checkpoint()
        request = Request(url, headers={'Accept-Encoding': 'identity'})
        context = _wget_tls_context() if parts.scheme in ('http', 'https') else None
        with urlopen(request, timeout=15, context=context) as response:
            if output:
                target = self.path_resolver.resolve_target_path(output)
            else:
                target = self.path_resolver.get_current_directory()

            if not output or os.path.isdir(target) or output.endswith(('/', os.sep)):
                response_name = response.headers.get_filename()
                if not response_name:
                    response_name = unquote(urlsplit(response.geturl()).path.rsplit('/', 1)[-1])
                filename = str(response_name or '').replace('\\', '/').rsplit('/', 1)[-1]
                filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename).rstrip(' .')
                if not filename or PureWindowsPath(filename).is_reserved():
                    filename = 'download.bin'
                target = os.path.join(target, filename)

            if conflict == 'stop' and os.path.lexists(target):
                return 0, f'Download target already exists: {target}'
            directory = os.path.dirname(target)
            os.makedirs(directory, exist_ok=True)
            headers = response.headers
            content_length = str(headers.get('Content-Length') or '').strip()
            total = int(content_length) if content_length.isdecimal() else None
            label = os.path.basename(target)
            size = f' ({format_bytes(total)})' if total is not None else ''
            self.emit_progress(f'Downloading {label}{size}')

            received = 0
            next_update = time.monotonic() + 1
            read = getattr(response, 'read1', response.read)
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.rch-wget-', suffix='.part',
                                             delete=False) as staged:
                staged_path = staged.name
                while True:
                    self._checkpoint()
                    chunk = read(256 * 1024)
                    if not chunk:
                        break
                    staged.write(chunk)
                    received += len(chunk)
                    now = time.monotonic()
                    if now >= next_update:
                        progress = format_bytes(received)
                        if total:
                            progress += f' / {format_bytes(total)} ({min(received * 100 // total, 100)}%)'
                        self.emit_progress(f'Downloaded {progress}')
                        next_update = now + 1

        if total is not None and received != total:
            return 0, f'Download incomplete: received {format_bytes(received)} of {format_bytes(total)}.'
        self._checkpoint()
        if conflict == 'replace':
            os.replace(staged_path, target)
        else:
            target = commit_download_file(staged_path, target, conflict)
        staged_path = None
        return 1, f'Downloaded {format_bytes(received)}\n{target}'
    except HTTPError as exc:
        exc.close()
        return 0, f'Download failed: HTTP {exc.code} ({exc.reason}). Check the URL and access permissions.'
    except CommandTimeoutError:
        raise
    except TimeoutError:
        return 0, 'Download timed out waiting for the remote server.'
    except (URLError, ssl.SSLCertVerificationError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, ssl.SSLCertVerificationError):
            return 0, f'HTTPS certificate verification failed on this Client: {reason.verify_message}'
        return 0, f'Unable to reach the download server: {reason}'
    except http.client.HTTPException:
        return 0, 'Download interrupted: the remote server closed the connection unexpectedly.'
    except FileExistsError:
        return 0, f'Download target already exists: {target}'
    except OSError as exc:
        return 0, f'Could not complete the download: {exc.strerror or exc}'
    except ValueError as exc:
        return 0, f'Download failed: {exc}'
    finally:
        if staged_path is not None:
            try:
                os.remove(staged_path)
            except FileNotFoundError:
                pass


def register_commands(registry):
    """Register declarations owned by this Common / Platform module."""
    registry.register(zip)
    registry.register(unzip)
    registry.register(download)
    registry.register(file_shred)
    registry.register(find)
    registry.register(wget)
