"""RCHCLI remote-file editing keeps the existing preview/save contract."""

import importlib.util
import io
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

CLI_DIR = pathlib.Path(__file__).resolve().parents[1] / 'rchcli'
sys.path.insert(0, str(CLI_DIR))
import rchcli_edit as edit_module

spec = importlib.util.spec_from_file_location('rchcli_under_edit_test', CLI_DIR / 'rchcli.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class ApiStub:
    timeout = 12

    def __init__(self, preview=None, save_error=None):
        self.preview = preview if preview is not None else {
            'type': 'text', 'content': 'original\r\n', 'encoding': 'utf-8',
            'truncated': False, 'editable': True,
        }
        self.save_error = save_error
        self.calls = []

    def request(self, method, path, payload, *, timeout=None):
        self.calls.append((method, path, payload, timeout))
        if path.endswith('/preview'):
            return self.preview
        if self.save_error:
            raise RuntimeError(self.save_error)
        return {'path': payload['path'], 'message': 'ok'}


def edit_with(api, mutate, path='"folder/my file.txt"'):
    editor = edit_module.RemoteFileEditor(api)

    def fake_run(args, *, check):
        draft = pathlib.Path(args[-1])
        if mutate is not None:
            mutate(draft)
        class Process:
            returncode = 0
        return Process()

    with patch.object(editor, '_editor_command', return_value=['vim']), \
         patch.object(edit_module.subprocess, 'run', side_effect=fake_run):
        return editor.edit('client/id', path)


class RemoteFileEditTests(unittest.TestCase):
    def test_real_api_json_envelope_and_request_timeout(self):
        import json
        class LocalOpener:
            def __init__(self):
                self.calls = []
            def open(self, req, timeout):
                payload = json.loads(req.data.decode('utf-8'))
                self.calls.append((req.get_full_url(), payload, timeout, req.get_header('Authorization')))
                if req.full_url.endswith('/preview'):
                    data = {'type': 'text', 'content': 'old', 'encoding': 'utf-8',
                            'editable': True, 'truncated': False}
                else:
                    data = {'path': payload['path'], 'message': 'success'}
                return io.BytesIO(json.dumps({'code': 0, 'data': data}).encode('utf-8'))
        api = cli.RchApi('http://localhost:8085', 'token', timeout=12)
        api.opener = LocalOpener()
        editor = edit_module.RemoteFileEditor(api)
        def run(args, *, check):
            pathlib.Path(args[-1]).write_text('new', encoding='utf-8')
            return type('Completed', (), {'returncode': 0})()
        with patch.object(editor, '_editor_command', return_value=['vim']), \
             patch.object(edit_module.subprocess, 'run', side_effect=run):
            self.assertIn('Saved remote file', editor.edit('mac/1', 'a.txt'))
        self.assertEqual(len(api.opener.calls), 2)
        self.assertEqual(api.opener.calls[0][0], 'http://localhost:8085/api/connections/mac%2F1/remote-files/preview')
        self.assertEqual(api.opener.calls[1][1], {'path': 'a.txt', 'content': 'new', 'encoding': 'utf-8'})
        self.assertTrue(all(c[2] == 120 and c[3] == 'Bearer token' for c in api.opener.calls))

    def test_existing_text_save_and_original_encoding(self):
        api = ApiStub(preview={
            'type': 'text', 'content': '旧值\r\n', 'encoding': 'utf-16-le',
            'editable': True, 'truncated': False,
        })
        msg = edit_with(api, lambda f: f.write_text('新值\r\n', encoding='utf-8', newline=''))
        self.assertIn('Saved remote file', msg)
        self.assertEqual(api.calls[0][1], '/api/connections/client%2Fid/remote-files/preview')
        self.assertEqual(api.calls[1][2], {
            'path': 'folder/my file.txt', 'content': '新值\r\n', 'encoding': 'utf-16-le',
        })
        self.assertGreaterEqual(api.calls[0][3], 120)
        self.assertGreaterEqual(api.calls[1][3], 120)

    def test_no_change_never_uploads(self):
        api = ApiStub()
        msg = edit_with(api, lambda f: None)
        self.assertIn('No changes', msg)
        self.assertEqual(len(api.calls), 1)

    def test_windows_backslashes_and_unquoted_spaces_survive(self):
        api = ApiStub()
        edit_with(api, lambda f: f.write_text('edited', encoding='utf-8'),
                  r'C:\Program Files\RCH\note.txt')
        self.assertEqual(api.calls[-1][2]['path'], r'C:\Program Files\RCH\note.txt')

    def test_truncated_or_non_editable_or_binary_refused_without_editor(self):
        for preview in (
            {'type': 'text', 'content': 'partial', 'editable': False, 'truncated': True},
            {'type': 'text', 'content': 'opaque', 'editable': False, 'truncated': False},
            {'type': 'image'},
        ):
            api = ApiStub(preview)
            with self.subTest(preview=preview), patch.object(edit_module.RemoteFileEditor, '_editor_command') as find_editor:
                with self.assertRaises(edit_module.RemoteEditError):
                    edit_module.RemoteFileEditor(api).edit('id', './file.txt')
                find_editor.assert_not_called()
                self.assertEqual(len(api.calls), 1)

    def test_save_failure_preserves_local_draft(self):
        api = ApiStub(save_error='offline')
        with self.assertRaisesRegex(edit_module.RemoteEditError, 'local draft kept') as caught:
            edit_with(api, lambda f: f.write_text('important edited content', encoding='utf-8'))
        # Error includes the actual recoverable file path.
        draft_name = str(caught.exception).split('local draft kept at ', 1)[1]
        draft = pathlib.Path(draft_name)
        try:
            self.assertEqual(draft.read_text(encoding='utf-8'), 'important edited content')
        finally:
            import shutil
            shutil.rmtree(draft.parent)

    def test_editor_nonzero_keeps_copy_and_does_not_save(self):
        api = ApiStub()
        editor = edit_module.RemoteFileEditor(api)
        class Failed:
            returncode = 2
        with patch.object(editor, '_editor_command', return_value=['vim']), \
             patch.object(edit_module.subprocess, 'run', return_value=Failed()):
            with self.assertRaisesRegex(edit_module.RemoteEditError, 'exited with code 2') as caught:
                editor.edit('id', 'note.txt')
        draft = pathlib.Path(str(caught.exception).split('local draft kept at ', 1)[1])
        try:
            self.assertTrue(draft.is_file())
            self.assertEqual(len(api.calls), 1)
        finally:
            import shutil
            shutil.rmtree(draft.parent)

    def test_invalid_local_encoding_preserves_draft(self):
        api = ApiStub()
        with self.assertRaisesRegex(edit_module.RemoteEditError, 'valid UTF-8') as caught:
            edit_with(api, lambda f: f.write_bytes(b'\xff\xfe'))
        draft = pathlib.Path(str(caught.exception).split('local draft kept at ', 1)[1])
        try:
            self.assertEqual(draft.read_bytes(), b'\xff\xfe')
            self.assertEqual(len(api.calls), 1)
        finally:
            import shutil
            shutil.rmtree(draft.parent)

    def test_requires_single_nonempty_path(self):
        for value in ('', '  ', '\x00', '""', '\n'):
            with self.subTest(value=value):
                with self.assertRaises(edit_module.RemoteEditError):
                    edit_module.RemoteFileEditor(ApiStub()).edit('id', value)

    def test_local_editor_missing_is_clear(self):
        with patch.dict(os.environ, {'VISUAL': '', 'EDITOR': ''}), \
             patch.object(edit_module.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(edit_module.RemoteEditError, 'No local vim/vi'):
                edit_module.RemoteFileEditor(ApiStub())._editor_command()

    def test_repl_intercepts_edit_only_in_client_session(self):
        lines = iter(['edit "my notes.txt"', 'bg', 'quit'])
        console = cli.RemoteConsole(ApiStub(), None, 'tab', reader=lambda _: next(lines),
                                    output=io.StringIO(), color='never')
        console.selected = {'client_id': 'client-id'}
        with patch.object(console, '_install_readline_completion', return_value=None), \
             patch.object(edit_module.RemoteFileEditor, 'edit', return_value='Saved remote file: my notes.txt') as edit:
            console.repl()
        edit.assert_called_once_with('client-id', '"my notes.txt"')
        self.assertIn('Saved remote file', console.output.getvalue())


if __name__ == '__main__':
    unittest.main()
