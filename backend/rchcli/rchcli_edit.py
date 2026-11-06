"""Edit a remote text file with the operator machine's terminal editor."""

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


class RemoteEditError(Exception):
    """A remote preview, local edit, or remote save could not be completed."""


class RemoteFileEditor:
    """Use Remote Files preview/save with a private local editor draft."""

    REQUEST_TIMEOUT = 120
    SUPPORTED_ENCODINGS = frozenset({'utf-8', 'utf-8-sig', 'utf-16-le', 'utf-16-be'})

    def __init__(self, api):
        self.api = api

    @staticmethod
    def _path(argument):
        path = str(argument or '').strip()
        if len(path) >= 2 and path[0] in ('"', "'") and path[-1] == path[0]:
            path = path[1:-1]
        if not path or '\x00' in path or '\n' in path or '\r' in path:
            raise RemoteEditError('Usage: edit <remote-file-path>')
        return path

    @staticmethod
    def _editor_command():
        if sys.platform == 'ios':
            raise RemoteEditError('A local terminal editor is unavailable on Pythonista')
        configured = os.environ.get('VISUAL') or os.environ.get('EDITOR')
        if configured:
            try:
                args = shlex.split(configured, posix=os.name != 'nt')
            except ValueError as exc:
                raise RemoteEditError('Invalid VISUAL/EDITOR command') from exc
            if os.name == 'nt' and args:
                args[0] = args[0].strip('"')
            if not args or not (shutil.which(args[0]) or os.path.isfile(args[0])):
                raise RemoteEditError('VISUAL/EDITOR executable was not found')
            return args
        for executable in ('vim', 'vi'):
            resolved = shutil.which(executable)
            if resolved:
                return [resolved]
        raise RemoteEditError('No local vim/vi found; install an editor or set VISUAL/EDITOR')

    def _request(self, client_id, action, payload):
        endpoint = '/api/connections/' + quote(client_id, safe='') + '/remote-files/' + action
        return self.api.request('POST', endpoint, payload, timeout=max(self.REQUEST_TIMEOUT, self.api.timeout))

    def edit(self, client_id, argument):
        path = self._path(argument)
        preview = self._request(client_id, 'preview', {'path': path})
        if not isinstance(preview, dict) or preview.get('type') != 'text':
            raise RemoteEditError('Only text files can be edited')
        if preview.get('truncated') or preview.get('editable') is not True:
            raise RemoteEditError('File exceeds the editable preview size or is not editable')
        content, codec = preview.get('content'), preview.get('encoding')
        if not isinstance(content, str) or codec not in self.SUPPORTED_ENCODINGS:
            raise RemoteEditError('Unsupported text content or encoding')
        editor = self._editor_command()

        name = path.replace('\\', '/').rsplit('/', 1)[-1]
        extension = os.path.splitext(name)[1]
        if not re.fullmatch(r'\.[A-Za-z0-9_-]{1,16}', extension):
            extension = '.txt'
        draft_dir = Path(tempfile.mkdtemp(prefix='rchcli-edit-'))
        draft = draft_dir / ('remote' + extension)
        keep_draft = True
        try:
            original = content.encode('utf-8')
            draft.write_bytes(original)
            result = subprocess.run(editor + [str(draft)], check=False)
            if result.returncode != 0:
                raise RemoteEditError(f'Local editor exited with code {result.returncode}')
            updated = draft.read_bytes()
            if updated == original:
                keep_draft = False
                return 'No changes; remote file was not saved'
            try:
                new_content = updated.decode('utf-8', errors='strict')
            except UnicodeDecodeError as exc:
                raise RemoteEditError('Edited file is not valid UTF-8') from exc
            if any(ord(char) < 32 and char not in '\t\r\n\f' for char in new_content):
                raise RemoteEditError('Edited file contains non-text control characters')
            self._request(client_id, 'save', {'path': path, 'content': new_content, 'encoding': codec})
            keep_draft = False
            return 'Saved remote file: ' + path
        except Exception as exc:
            raise RemoteEditError(f'{exc}; local draft kept at {draft}') from exc
        finally:
            if not keep_draft:
                shutil.rmtree(draft_dir)
