"""Common file commands available on every Python Client."""
import fnmatch
import http.client
import os
import re
import tempfile
import time
from pathlib import PureWindowsPath
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from client.commands.acmd.decorators import argument_command
from client.commands.acmd.standalone.zip import zip as zip_command
from client.commands.acmd.standalone.unzip import unzip as unzip_command
from client.commands.runtime.interrupts import cancel_policy
from client.runtime.execution.context import CommandTimeoutError
from core.command_completion.models import CompletionSpec
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.formatting import format_bytes


FIND_SPEC = ArgumentCommandSpec(
    name='find',
    description='Find files and directories recursively by keyword or wildcard',
    options=[
        ArgumentOptionSpec('path', 'str', default='.', positional_index=0,
                           completion=CompletionSpec('filesystem', ('directory',)),
                           help_text='Search directory (default: current directory)'),
        ArgumentOptionSpec('keyword', 'str', required=True, allow_empty=False,
                           help_text='Case-insensitive name substring or wildcard (e.g. *.jpg)'),
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
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd wget https://example.com/report.pdf -o ./report.pdf'],
)


class ACMDArchiveCommands:
    zip = zip_command
    unzip = unzip_command


class ACMDFileCommands(ACMDArchiveCommands):
    @argument_command('find', spec=FIND_SPEC)
    @cancel_policy('cooperative')
    def find(self, args_dict):
        self._set_cancel_policy('cooperative')
        root = self.path_resolver.require_existing_directory(args_dict['path'])
        keyword = args_dict['keyword'].strip().casefold()
        glob = any(char in keyword for char in '*?[')
        matches = []

        for directory, dirs, files in self._iter_checked(os.walk(root)):
            dirs.sort(key=str.casefold)
            for name in self._iter_checked(sorted(dirs + files, key=str.casefold), check_interval=64):
                normalized = name.casefold()
                matched = fnmatch.fnmatchcase(normalized, keyword) if glob else keyword in normalized
                if matched:
                    matches.append(os.path.join(directory, name))

        return 1, '\n'.join(matches) if matches else 'No matches found.'

    @argument_command('wget', spec=WGET_SPEC, output='stream')
    @cancel_policy('cooperative')
    def wget(self, args_dict):
        self._set_cancel_policy('cooperative')
        url = args_dict['url'].strip()
        output = args_dict['output'].strip()
        staged_path = None
        try:
            parts = urlsplit(url)
            if parts.scheme not in ('http', 'https', 'ftp') or not parts.hostname:
                return 0, 'Enter a valid HTTP, HTTPS or FTP URL.'
            self._checkpoint()
            request = Request(url, headers={'Accept-Encoding': 'identity'})
            with urlopen(request, timeout=15) as response:
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
            os.replace(staged_path, target)
            staged_path = None
            return 1, f'Downloaded {format_bytes(received)}\n{target}'
        except HTTPError as exc:
            exc.close()
            return 0, f'Download failed: HTTP {exc.code} ({exc.reason}). Check the URL and access permissions.'
        except CommandTimeoutError:
            raise
        except TimeoutError:
            return 0, 'Download timed out waiting for the remote server.'
        except URLError as exc:
            return 0, f'Unable to reach the download server: {exc.reason}'
        except http.client.HTTPException:
            return 0, 'Download interrupted: the remote server closed the connection unexpectedly.'
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
